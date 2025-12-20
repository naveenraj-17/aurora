
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import json
import os
from duckduckgo_search import DDGS
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import sys
from core.config import load_settings

# Initialize MCP Server
app = Server("browser-mcp-server")

# Playwright Global Context
browser = None
context = None
playwright = None
_current_headless_mode = None

async def get_browser_context():
    global browser, context, playwright, _current_headless_mode
    
    # Load settings to check for visibility preference
    current_settings = load_settings()
    # If show_browser is True, headless should be False
    headless = not current_settings.get("show_browser", False) 

    # If mode changed, close existing browser to restart
    if browser and _current_headless_mode is not None and _current_headless_mode != headless:
        print(f"DEBUG: Switching browser mode (Headless: {_current_headless_mode} -> {headless}). Restarting...", file=sys.stderr)
        await browser.close()
        browser = None
        context = None

    if not playwright:
        playwright = await async_playwright().start()
    
    if not browser:
        print(f"DEBUG: Launching Browser (Headless={headless})...", file=sys.stderr)
        try:
            browser = await playwright.chromium.launch(headless=headless, args=['--no-sandbox', '--disable-setuid-sandbox'])
            _current_headless_mode = headless
        except Exception as e:
            if not headless:
                print(f"DEBUG: Failed to launch headed browser (likely WSL/Display issue): {e}", file=sys.stderr)
                print("DEBUG: Falling back to HEADLESS mode...", file=sys.stderr)
                browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
                _current_headless_mode = True
            else:
                raise e
        
    if not context:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        
    return context

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_web",
            description="Search the web for information using DuckDuckGo. Returns a list of relevant results with titles and URLs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (max 10)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="visit_page",
            description="Visit a specific URL and extract its text content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to visit"
                    }
                },
                "required": ["url"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    try:
        if name == "search_web":
            query = arguments.get("query")
            limit = arguments.get("limit", 5)
            
            # Check for visual mode
            current_settings = load_settings()
            show_browser = current_settings.get("show_browser", False)
            print(f"DEBUG: browser_agent loaded settings -> show_browser={show_browser}", file=sys.stderr)

            if show_browser:
                print(f"DEBUG: Visual Searching web for '{query}'...", file=sys.stderr)
                try:
                    ctx = await get_browser_context()
                    page = await ctx.new_page()
                    
                    # Navigate to Google
                    await page.goto("https://www.google.com", wait_until="domcontentloaded")
                    
                    # Handle "Before you continue" cookie consent if it appears (common in EU/headless)
                    try:
                        await page.click('button:has-text("Reject all")', timeout=2000)
                    except:
                        pass

                    # Google Search Input (textarea is modern, input is legacy)
                    try:
                        await page.fill('textarea[name="q"]', query, timeout=2000)
                    except:
                        await page.fill('input[name="q"]', query)
                        
                    await page.press('textarea[name="q"]' if await page.is_visible('textarea[name="q"]') else 'input[name="q"]', 'Enter')
                    
                    # Wait for results
                    try:
                         await page.wait_for_selector('div#search', timeout=5000) 
                    except:
                         print("DEBUG: Google Selector timeout, attempting to scrape anyway...", file=sys.stderr)
                    
                    await page.wait_for_timeout(2000) 

                    # Scrape Google Results
                    results_data = await page.evaluate("""() => {
                        const results = [];
                        // Google standard results
                        document.querySelectorAll('div.g').forEach((el, index) => {
                            if (index >= 6) return; // Limit to 6
                            const titleEl = el.querySelector('h3');
                            const linkEl = el.querySelector('a');
                            const snippetEl = el.querySelector('div[style*="-webkit-line-clamp"]'); 
                            
                            if (titleEl && linkEl) {
                                results.push({
                                    title: titleEl.innerText,
                                    href: linkEl.href,
                                    body: snippetEl ? snippetEl.innerText : el.innerText.substring(0, 100) + "..."
                                });
                            }
                        });
                        return results;
                    }""")
                    
                    if not results_data:
                        # Fallback to API if visual scrape failed
                        print("DEBUG: Visual scrape yielded no data. Falling back to API search...", file=sys.stderr)
                    else:
                        summary = "Google Search Results (Visual):\n"
                        for r in results_data:
                            summary += f"- [{r['title']}]({r['href']}): {r['body']}\n"
                        return [types.TextContent(type="text", text=summary)]

                except Exception as e:
                     import time
                     print(f"visual_search_error: {e}", file=sys.stderr)
                     if 'page' in locals():
                         await page.close()
                     # Fall through to API logic below
                
            # Default / Headless / Fallback
            # Clean query for better API results (DDGS struggles with "recent")
            clean_query = query.lower().replace("recent", "").replace("latest", "").strip()
            if not clean_query: # If query was ONLY "recent", keep it original
                clean_query = query
                
            print(f"DEBUG: Headless Searching web for '{clean_query}'...", file=sys.stderr)
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(clean_query, max_results=limit))
                
                if not results:
                     return [types.TextContent(type="text", text="No results found via API.")]

                summary = "Search Results:\n"
                if results:
                    print(f"DEBUG: First Result: {results[0]}", file=sys.stderr)
                
                for r in results:
                    summary += f"- [{r['title']}]({r['href']}): {r['body']}\n"
                
                summary += "\nSYSTEM NOTE: These are all the available results. Do not retry the same search."
                return [types.TextContent(type="text", text=summary)]
            except Exception as e:
                 print(f"api_search_error: {e}", file=sys.stderr)
                 return [types.TextContent(type="text", text=f"Search failed completely: {e}")]

        elif name == "visit_page":
            url = arguments.get("url")
            print(f"DEBUG: Visiting {url}...", file=sys.stderr)
            
            ctx = await get_browser_context()
            page = await ctx.new_page()
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait a bit for dynamic content
                await page.wait_for_timeout(2000) 
                
                content = await page.content()
                
                # HTML to Markdown/Text
                soup = BeautifulSoup(content, 'html.parser')
                
                # Remove scripts and styles
                for script in soup(["script", "style", "nav", "footer", "header"]):
                    script.extract()
                    
                text = soup.get_text()
                
                # Clean up whitespace
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                clean_text = '\n'.join(chunk for chunk in chunks if chunk)
                
                return [types.TextContent(type="text", text=clean_text[:50000])] # Limit return size
                
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error visiting page: {e}")]
            finally:
                await page.close()

    except Exception as e:
        return [types.TextContent(type="text", text=f"Error executing tool: {e}")]
    
    raise ValueError(f"Tool {name} not found")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
