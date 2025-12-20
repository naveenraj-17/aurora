import os
import sys
import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import httpx
from services.google import get_auth_url, finish_auth
try:
    from core.memory import MemoryStore
except ImportError:
    print("Warning: MemoryStore dependencies not found. Memory disabled.")
    MemoryStore = None

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3" 
REDIRECT_URI = "http://localhost:3000/auth/callback" 

# Agent Configuration
AGENTS = {
    "gmail": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "gmail.py"),
    "time": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "time.py"),
    "drive": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "drive.py"),
    "calendar": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "calendar_agent.py"),
    "local_file_agent": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "local_file.py"),
    "browser": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "browser.py"),
}

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    intent: str = "chat" # chat, list_emails, render_email, list_files, list_events, request_auth, list_local_files, render_local_file
    data: dict | None = None

# Global variables
# Map of client_name -> session
agent_sessions: dict[str, ClientSession] = {}
# Map of tool_name -> client_name
tool_router: dict[str, str] = {}
exit_stack = None
memory_store = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global exit_stack
    print("Starting Multi-Agent Orchestrator...")
    
    from contextlib import AsyncExitStack
    exit_stack = AsyncExitStack()
    
    try:
        for agent_name, script_path in AGENTS.items():
            print(f"Connecting to {agent_name} agent at {script_path}...")
            
            # Prepare environment with PYTHONPATH specifically pointing to backend root
            # This is crucial so agents can assume 'services' and 'core' are importable
            env = os.environ.copy()
            backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env["PYTHONPATH"] = backend_root + os.pathsep + env.get("PYTHONPATH", "")

            server_params = StdioServerParameters(
                command=sys.executable,
                args=[script_path],
                env=env
            )
            
            read, write = await exit_stack.enter_async_context(stdio_client(server_params))
            session = await exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            
            agent_sessions[agent_name] = session
            
            # Register tools
            tools = await session.list_tools()
            for tool in tools.tools:
                tool_router[tool.name] = agent_name
                print(f"  Registered tool: {tool.name} -> {agent_name}")
                
        # Initialize Memory Store
        if MemoryStore:
            print("Initializing Memory Store...")
            global memory_store
            memory_store = MemoryStore()
        
        print("All agents connected.")
        yield
        
    except Exception as e:
        print(f"Error starting agents: {e}")
        yield
    finally:
        print("Shutting down agents...")
        if exit_stack:
            await exit_stack.aclose()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Auth Endpoints ---
@app.get("/auth/login")
async def login():
    try:
        auth_url = get_auth_url(redirect_uri=REDIRECT_URI)
        return RedirectResponse(auth_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.responses import RedirectResponse, FileResponse

# ... imports ...

@app.get("/auth/callback")
async def callback(code: str):
    try:
        finish_auth(code=code, redirect_uri=REDIRECT_URI)
        return RedirectResponse("http://localhost:3000") 
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Settings & Config Helpers ---
# --- Settings & Config Helpers ---
from core.config import load_settings, SETTINGS_FILE

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "token.json")

class Settings(BaseModel):
    agent_name: str
    model: str = "mistral" # Default model (Ollama or Cloud)
    mode: str = "local" # "local" or "cloud"
    openai_key: str = ""
    anthropic_key: str = ""
    gemini_key: str = ""
    show_browser: bool = False

def save_settings(settings: dict):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)

@app.get("/api/status")
async def get_status():
    # In a real system, we'd ping each agent. For now, check if they are in the AGENTS dict
    agents_status = {}
    for name in AGENTS.keys():
        agents_status[name] = "online"
    
    current_settings = load_settings()
    return {
        "agents": agents_status, 
        "overall": "operational", 
        "model": current_settings.get("model", "mistral"),
        "mode": current_settings.get("mode", "local")
    }

@app.get("/api/settings")
async def get_settings():
    return load_settings()

@app.post("/api/settings")
async def update_settings(settings: Settings):
    print(f"DEBUG: update_settings called with: {settings.dict()}")
    data = settings.dict()
    save_settings(data)
    return data

class GoogleCredsRequest(BaseModel):
    content: str # Raw JSON string or dict

@app.post("/api/setup/google-credentials")
async def upload_google_creds(request: Request):
    try:
        data = await request.json()
        print(f"DEBUG: Received credentials upload (Type: {type(data)})")
        
        # Ensure it's valid JSON
        if isinstance(data, str):
             parsed = json.loads(data)
        else:
             parsed = data
             
        # Write to file
        with open(CREDENTIALS_FILE, 'w') as f:
            json.dump(parsed, f, indent=4)
            
        return {"status": "success", "message": "Credentials saved successfully."}
    except Exception as e:
        print(f"Error saving credentials: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

@app.post("/api/setup/google-token")
async def upload_google_token(request: Request):
    try:
        data = await request.json()
        print(f"DEBUG: Received token upload (Type: {type(data)})")
        
        # Ensure it's valid JSON
        if isinstance(data, str):
             parsed = json.loads(data)
        else:
             parsed = data
             
        # Write to file
        with open(TOKEN_FILE, 'w') as f:
            json.dump(parsed, f, indent=4)
            
        return {"status": "success", "message": "Token saved successfully."}
    except Exception as e:
        print(f"Error saving token: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

@app.get("/api/models")
async def get_models():
    """Fetches available models from Ollama + Cloud Options."""
    models = []
    
    # 1. Cloud Models (Hardcoded)
    models.extend([
        "gpt-4o", "gpt-4-turbo", 
        "claude-3-5-sonnet", 
        "gemini-3-pro-preview", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"
    ])
    
    # 2. Local Models (Ollama)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if response.status_code == 200:
                ollama_models = [m["name"] for m in response.json().get("models", [])]
                models.extend(ollama_models)
    except Exception as e:
        print(f"Error fetching models: {e}")
        models.extend(["mistral", "llama3"]) # Fallback if Ollama down
        
    return {"models": models}

@app.get("/api/config")
async def get_config():
    if not os.path.exists(CREDENTIALS_FILE):
        return {"error": "Credentials not found"}
    
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            creds = json.load(f)
            # Support both 'web' and 'installed' (desktop) application types
            app_info = creds.get("web") or creds.get("installed", {})
            
            # Return masked data
            return {
                "client_id": app_info.get("client_id", "")[:10] + "..." + app_info.get("client_id", "")[-10:],
                "project_id": app_info.get("project_id", ""),
                "auth_uri": app_info.get("auth_uri", ""),
                "token_uri": app_info.get("token_uri", "")
            }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/file")
async def get_file(path: str):
    """
    Serve a local file.
    SECURITY WARNING: In a production app, this MUST validate 'path' 
    to prevent Directory Traversal attacks. For this local POC/agent, 
    we allow reading user files.
    """
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)

# --- Chat Logic ---
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if not agent_sessions:
        raise HTTPException(status_code=500, detail="No agents connected")
    
    user_message = request.message
    
    # 1. Aggregate Tools
    all_tools = []
    for session in agent_sessions.values():
        result = await session.list_tools()
        all_tools.extend(result.tools)
    
    # 2. System Prompt
    tools_json = str([{'name': t.name, 'description': t.description, 'schema': t.inputSchema} for t in all_tools])
    
    system_prompt_text = (
        "You are a helpful assistant with access to multiple tools.\n"
        f"Available Tools:\n{tools_json}\n\n"
        "Routing Rules:\n"
        "- IMPORTANT: If user asks for 'all', 'every', or 'everything', set 'limit' to 100. Default limit is 5 if not specified.\n"
        "- If user asks for emails, use 'list_emails'. Extract 'limit'.\n"
        "- If user searches emails, use 'list_emails' with 'query' (e.g. 'from:John', 'is:unread', 'is:important').\n"
        "- If user asks to *summarize* multiple emails, use 'get_recent_emails_content'. extract 'limit' AND 'query'. e.g. 'summarize last 5 important emails' -> limit=5, query='is:important'.\n"
        "- If user asks to read an email, use 'read_email'.\n"
        "- If user asks for Drive files, use 'list_files'. Extract 'limit'.\n"
        "- If user searches Drive, use 'list_files' with 'query'. Syntax: \"name contains 'foo'\", \"mimeType = 'application/pdf'\".\n"
        "- If user asks for Calendar events, use 'list_upcoming_events'. Extract 'limit'.\n"
        "- If user asks for time, use 'get_current_time'.\n"
        "- If user searches local files, use 'list_local_files'.\n"
        "- If user asks to read a local file, use 'read_local_file'.\n"
        "- If user asks to JUST open a file, use 'open_file'.\n"
        "- If user asks to locate a file, use 'locate_file'.\n"
        "- If user asks to create a calendar event/meeting, use 'create_event'.\n"
        "- If user asks to create a Drive file/folder/doc, use 'create_file'. MimeTypes: Folder='application/vnd.google-apps.folder', Doc='application/vnd.google-apps.document', Sheet='application/vnd.google-apps.spreadsheet'.\n"
        "- If user asks to read or summarize a *Drive* file, use 'read_file_content'.\n"
        "- If user asks to search the web/internet, finds info, or research, use 'search_web'. Extract the FULL query topic (e.g. 'search recent space news' -> query='recent space news').\n"
        "- If user asks to visit a website/link or read a webpage, use 'visit_page'.\n\n"
        "STRATEGY - MULTI-STEP REASONING:\n"
        "1. You can call tools multiple times. e.g. List files -> Find target ID -> Read content -> Create Summary Doc.\n"
        "2. If you need information from a previous step, DO NOT make it up. Use the Tool Output.\n"
        "3. If a tool fails, explain why and try a different approach or ask the user.\n\n"
        "RESPONSE FORMAT:\n"
        "1. IF you need to use a tool: Respond ONLY with a JSON object: {\"tool\": \"tool_name\", \"arguments\": {...}}\n"
        "2. IF you can answer directly: Respond with PLAIN TEXT.\n"
        "3. **CRITICAL**: When providing links (to Docs, Files, Emails), ALWAYS format them as Markdown: `[Link Title](URL)`. Do NOT simply paste the URL.\n"
        "4. **Email Sending Policy**: \n"
        "   - **DRAFTING**: If user asks to send/draft, you MUST use `draft_email` first. Generate full content yourself. STOP after calling it.\n"
        "   - **SENDING**: You may ONLY use `send_email` if the user input explicitly starts with \"Confirmed.\".\n"
        "   - If you see \"Confirmed. Please immediately execute...\", you MUST call `send_email` immediately.\n"
        "5. **STOPPING**: If you have completed the request (e.g. drafted the email, listed files), respond with a PLAIN TEXT summary. DO NOT call the same tool again.\n"
        "6. **NO LOOPING**: If you have performed a search and got results, DO NOT call `search_web` again with the same query. Use the existing results.\n"
    )

    current_settings = load_settings()
    current_model = current_settings.get("model", "mistral")
    mode = current_settings.get("mode", "local")

    # --- Helper: Cloud API Callers (Inlined for simplicity or keep existing) ---
    async def call_openai(model, messages, api_key):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": messages},
                timeout=60.0
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def call_anthropic(model, messages, system, api_key):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "messages": messages, "system": system, "max_tokens": 4096},
                timeout=60.0
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    async def call_gemini(model, prompt, system, api_key):
        full_prompt = f"System: {system}\n\nUser Check History: {prompt}"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={"contents": [{"parts": [{"text": full_prompt}]}]},
                timeout=60.0
            )
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    async def generate_response(prompt_msg, sys_prompt):
        if mode == "cloud":
            try:
                # Construct messages list for cloud providers that support it
                messages = [{"role": "user", "content": prompt_msg}]
                
                if current_model.startswith("gpt"):
                    return await call_openai(current_model, [{"role": "system", "content": sys_prompt}] + messages, current_settings.get("openai_key"))
                elif current_model.startswith("claude"):
                    return await call_anthropic(current_model, messages, sys_prompt, current_settings.get("anthropic_key"))
                elif current_model.startswith("gemini"):
                    return await call_gemini(current_model, prompt_msg, sys_prompt, current_settings.get("gemini_key")) # Simplification for Gemini REST
                else:
                    return "Error: Unknown cloud model selected."
            except Exception as e:
                return f"Cloud API Error: {str(e)}"
        
        # Local Ollama
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": current_model,
                        "prompt": prompt_msg,
                        "system": sys_prompt,
                        "stream": False
                    },
                    timeout=None
                )
                response.raise_for_status()
                return response.json().get("response", "")
            except Exception as e:
                return f"Local Agent Error: {e}"

    # --- ReAct Loop ---
    MAX_TURNS = 5
    
    # 3. Retrieve Memory
    relevant_memories = []
    if memory_store:
        relevant_memories = memory_store.query_memory(user_message)
    
    memory_context = ""
    if relevant_memories:
        memory_context = "\nRelevant Past Conversations:\n" + "\n".join(relevant_memories) + "\n"

    current_context = f"{memory_context}User Request: {user_message}\n"
    final_response = ""
    last_intent = "chat"
    last_data = None
    
    print(f"--- Starting ReAct Loop for: {user_message} ---")
    last_tool_signature = ""
    tool_repetition_counts = {}

    async with httpx.AsyncClient() as client:
        for turn in range(MAX_TURNS):
            print(f"Turn {turn + 1}/{MAX_TURNS}")
            
            # Ask LLM
            llm_output = await generate_response(current_context, system_prompt_text)
            print(f"DEBUG: LLM Output: {llm_output[:100]}...") # Log first 100 chars
            
            # Parse Tool Call
            import re
            tool_call = None
            json_error = None
            
            try:
                cleaned_output = llm_output.replace("```json", "").replace("```", "").strip()
                json_match = re.search(r'\{.*\}', cleaned_output, re.DOTALL)
                if json_match:
                    tool_call = json.loads(json_match.group(0))
            except Exception as e:
                json_error = str(e)

            if json_error:
                print(f"DEBUG: JSON Error: {json_error}")
                current_context += f"\nSystem: JSON Parsing Error: {json_error}. You generated invalid JSON (likely unescaped quotes or newlines). Please Try Again with valid, escaped JSON.\n"
                continue

            if tool_call and isinstance(tool_call, dict) and "tool" in tool_call:
                # It's a tool call!
                tool_name = tool_call["tool"]
                tool_args = tool_call.get("arguments", {})
                print(f"DEBUG: EXTRACTED TOOL ARGS: {tool_name} -> {tool_args}")
                
                if tool_name not in tool_router:
                     # Hallucinated tool, append error and continue
                     current_context += f"\nSystem: Error - Tool '{tool_name}' not found. Please try a valid tool.\n"
                     continue

                # Loop Guard with Repetition Tolerance
                current_tool_signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                
                # Increment count
                tool_repetition_counts[current_tool_signature] = tool_repetition_counts.get(current_tool_signature, 0) + 1
                
                if tool_repetition_counts[current_tool_signature] > 2: # Allow 1st call + 1 retry (total 2). 3rd call triggers guard.
                    print(f"DEBUG: Loop detected (>2 calls). Identical tool call {tool_name}. Warning LLM.", file=sys.stderr)
                    current_context += f"\nSystem: You are stuck in a loop calling '{tool_name}' with the same arguments. **STOP**. The results are already in the conversation history above. Scroll up and use them to answer the user.\n"
                    # Do NOT break. Give LLM a chance to recover.
                    continue
                
                last_tool_signature = current_tool_signature

                agent_name = tool_router[tool_name]
                session = agent_sessions[agent_name]
                
                print(f"Executing {tool_name} on {agent_name}...")
                try:
                    result = await session.call_tool(tool_name, tool_args)
                    raw_output = result.content[0].text
                    
                    # Store intent/data for frontend if it's the *last* interesting thing
                    # But for intermediate steps, we mainly care about text output
                    try:
                        parsed = json.loads(raw_output)
                        if "error" in parsed and parsed["error"] == "auth_required":
                             return ChatResponse(response="Authentication required.", intent="request_auth", data=parsed)
                        
                        # Special handling for get_recent_emails_content to emphasize count
                        if tool_name == "get_recent_emails_content" and isinstance(parsed, dict) and "emails" in parsed:
                            emails = parsed.get("emails", [])
                            email_texts = [f"Email {i+1}:\nSubject: {e.get('subject', 'N/A')}\nFrom: {e.get('from', 'N/A')}\nDate: {e.get('date', 'N/A')}\nBody: {e.get('body', 'N/A')}" for i, e in enumerate(emails)]
                            raw_output = f"Here is the content of the {len(emails)} emails found (Note: This might be fewer than requested). FAST AND CONCISELY Summarize them. EXPLICITLY mention that you found {len(emails)} emails matching the query:\n" + "\n".join(email_texts)
                        
                        # Set intent for frontend logic (e.g. if we list files, we want the UI to show them)
                        if tool_name.startswith("list_") or tool_name.startswith("read_") or tool_name.startswith("create_") or tool_name == "draft_email" or tool_name == "send_email":
                             last_intent = tool_name
                             if tool_name == "list_upcoming_events": last_intent = "list_events" # normalize
                             last_data = parsed

                        if tool_name == "search_web":
                             last_intent = "search_web"
                             last_data = parsed

                        if tool_name == "search_web":
                            last_intent = "search_web"
                            last_data = parsed

                    except:
                        pass

                    # Append Result to Context
                    # Increase truncation limit to 50k to allow full email contents to be passed to next steps
                    display_output = raw_output[:50000] + "...(truncated)" if len(raw_output) > 50000 else raw_output
                    print(f"DEBUG: Tool Output Length: {len(raw_output)}")
                    current_context += f"\nTool '{tool_name}' Output: {display_output}\n"
                    
                except Exception as e:
                    current_context += f"\nSystem: Error executing tool {tool_name}: {str(e)}\n"
            
            else:
                # No tool call, this is the final answer
                final_response = llm_output
                break
        
        if not final_response:
             final_response = "I completed the requested actions." # Fallback if loop finishes with tool usage


        
    # 4. Save to Memory (Background Task ideal, but inline for POC)
    if memory_store and final_response:
        memory_store.add_memory("user", user_message)
        memory_store.add_memory("assistant", final_response)
        
    return ChatResponse(
        response=final_response,
        intent=last_intent,
        data=last_data
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
