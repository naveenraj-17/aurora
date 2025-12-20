
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import json
from services.google import list_messages, get_message, UnauthenticatedError

# Initialize MCP Server
app = Server("email-mcp-server")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_emails",
            description="List recent emails. Returns a list of emails with ID, sender, subject, and snippet. Can filter by query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of emails to return (default 5)",
                        "default": 5
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query to filter emails (e.g., 'subject:insurance', 'from:boss@company.com')",
                    }
                }
            }
        ),
        types.Tool(
            name="read_email",
            description="Read the full content of a specific email by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": "The ID of the email to read"
                    }
                },
                "required": ["email_id"]
            }
        ),
        types.Tool(
            name="get_recent_emails_content",
            description="Fetch the text content of multiple recent emails for summarization.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of emails to fetch (default 5, max 10)",
                        "default": 5
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query to filter emails (e.g. 'is:unread', 'category:primary', 'from:sender')."
                    }
                }
            }
        ),
        types.Tool(
            name="draft_email",
            description="Draft an email for review. Returns the draft content. Use this BEFORE sending.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"}
                },
                "required": ["to", "subject", "body"]
            }
        ),
        types.Tool(
            name="send_email",
            description="Send an email immediately. Use AFTER draft confirmation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "cc": {"type": "string", "description": "CC recipients (comma separated)"},
                    "bcc": {"type": "string", "description": "BCC recipients (comma separated)"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"}
                },
                "required": ["to", "subject", "body"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    try:
        if name == "list_emails":
            limit = arguments.get("limit", 5)
            query = arguments.get("query")
            
            emails = list_messages(query=query, limit=limit)
            
            if not emails:
                 return [types.TextContent(type="text", text=json.dumps({"emails": []}))]

            return [types.TextContent(type="text", text=json.dumps({"emails": emails}))]

        elif name == "get_recent_emails_content":
            try:
                limit = int(arguments.get("limit", 5))
            except:
                limit = 5
            limit = min(limit, 10) # Cap at 10 to avoid huge context
            query = arguments.get("query")
            
            # 1. List IDs
            msgs = list_messages(query=query, limit=limit)
            if not msgs:
                return [types.TextContent(type="text", text="No emails found.")]
                
            # 2. Fetch Content for each
            results = []
            for m in msgs:
                full_email = get_message(m['id'])
                if full_email:
                    results.append({
                        "from": full_email.get('sender'),
                        "subject": full_email.get('subject'),
                        "date": full_email.get('date'),
                        "body": full_email.get('body', '')[:1000] # Truncate body to save tokens
                    })
            
            return [types.TextContent(type="text", text=json.dumps({"emails": results}))]
        
        elif name == "read_email":
            email_id = arguments.get("email_id")
            if not email_id:
                raise ValueError("email_id is required")
            
            email = get_message(email_id)
            if not email:
                return [types.TextContent(type="text", text=json.dumps({"error": f"Email with ID {email_id} not found."}))]
            
            return [types.TextContent(type="text", text=json.dumps(email))]

        elif name == "draft_email":
            # Just echo back the arguments so the frontend can display them
            return [types.TextContent(type="text", text=json.dumps(arguments))]

        elif name == "send_email":
            to = arguments.get("to")
            cc = arguments.get("cc")
            bcc = arguments.get("bcc")
            subject = arguments.get("subject")
            body = arguments.get("body")
            
            from services.google import send_email
            result = send_email(to, subject, body, cc=cc, bcc=bcc)
            
            if result:
                 return [types.TextContent(type="text", text=json.dumps({"status": "sent", "id": result['id']}))]
            else:
                 return [types.TextContent(type="text", text=json.dumps({"error": "Failed to send email."}))]
    
    except UnauthenticatedError:
        return [types.TextContent(type="text", text=json.dumps({"error": "auth_required", "auth_url": "http://localhost:3000/auth/login"}))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error executing tool: {e}")]
    
    raise ValueError(f"Tool {name} not found")

async def main():
    # Run the server using stdin/stdout transport
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
