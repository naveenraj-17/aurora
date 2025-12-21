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

from collections import deque
conversation_history = deque(maxlen=10) # Keep last 10 turns

def get_recent_history_text():
    if not conversation_history:
        return ""
    
    history_str = "\n--- Recent Conversation History (Most Recent Last) ---\n"
    for turn in conversation_history:
        history_str += f"User: {turn['user']}\n"
        if turn['tools']:
             history_str += f"Tools Used: {turn['tools']}\n"
        history_str += f"Assistant: {turn['assistant']}\n"
    history_str += "--- End of History ---\n"
    return history_str

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
    cloud_models = [
        "gpt-4o", "gpt-4-turbo", 
        "claude-3-5-sonnet", 
        "gemini-3-pro-preview", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"
    ]
    
    local_models = []
    
    # 2. Local Models (Ollama)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if response.status_code == 200:
                local_models = [m["name"] for m in response.json().get("models", [])]
    except Exception as e:
        print(f"Error fetching models: {e}")
        local_models = ["mistral", "llama3"] # Fallback if Ollama down
        
    return {"local": local_models, "cloud": cloud_models}

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

@app.delete("/api/history/recent")
async def clear_recent_history():
    """Clears the short-term in-memory session history."""
    conversation_history.clear()
    return {"status": "success", "message": "Recent session history cleared."}

@app.delete("/api/history/all")
async def clear_all_history():
    """Clears BOTH short-term session history AND long-term ChromaDB memory."""
    conversation_history.clear()
    if memory_store:
        success = memory_store.clear_memory()
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear long-term memory.")
    return {"status": "success", "message": "All history (Recent + Long-term) cleared."}

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
    
    system_prompt_text = (f"""
        You are a smart Personal Assistant Agent capable of managing emails, files, calendars, and web searches.

        ### YOUR GOAL
        Execute the user's intent by calling the correct tool with PRECISE parameters. If you have the data, summarize it clearly.

        ### AVAILABLE TOOLS
        {tools_json}

        ### 1. CRITICAL RULES: PARAMETER EXTRACTION
        **You must follow this logic tree for the 'limit' parameter:**
        * **IF** user says "all", "every", "everything" -> Set `limit` to **100**.
        * **IF** user specifies a number (e.g., "3 emails", "10 files") -> Set `limit` to that **EXACT NUMBER**.
        * **IF** user implies a singular item (e.g., "the last email", "the file") -> Set `limit` to **1**.
        * **ELSE** (no number specified) -> Set `limit` to **5** (Default).

        ### 2. CRITICAL RULES: QUERY CONSTRUCTION
        * **Filtering:** Never fetch "all" to filter manually. You MUST use the `query` parameter.
            * "Important emails" -> `query="is:important"`
            * "Unread emails" -> `query="is:unread"`
            * "Sent emails" -> `query="is:sent"`
            * "PDFs in Drive" -> `query="mimeType = 'application/pdf'"`
        * **Web Search:** Extract only the core topic.
            * "Search for news about AI" -> `query="news about AI"` (NOT "search for...")

        ### 3. TOOL ROUTING GUIDE (Use this to choose the right tool)

        **EMAIL:**
        * User wants to see a *list* of headers/subjects? -> `list_emails`
        * User wants to *summarize* or *read* multiple emails? -> `get_recent_emails_content`
        * User wants to read a *specific* email (by ID)? -> `read_email` (DO NOT use 'get_email_content' - it does not exist)
        * User wants to write/draft? -> `draft_email` (ALWAYS draft first. The tool will return the draft JSON. **STOP HERE**. Ask user to confirm. DO NOT call `send_email` in the same turn.)
        * User says "Confirmed" or asks to SEND? -> `send_email` (IMMEDIATE ACTION. OUTPUT JSON ONLY. {{ "tool": "send_email", ... }}. DO NOT EXPLAIN.)

        **DRIVE & FILES:**
        * User wants to find/list files? -> `list_files`
        * User wants to read/summarize a Drive file? -> `read_file_content`
        * User wants to create a Doc/Sheet? -> `create_file`
        * User wants to search *local* computer files? -> `list_local_files`
        * User wants to read a *local* file? -> `read_local_file`

        **CALENDAR & WEB:**
        * User asks about schedule/meetings? -> `list_upcoming_events`
        * User asks to set a meeting? -> `create_event`
        * User asks for information, news, or facts? -> `search_web`
        * User asks to read a specific URL? -> `visit_page`

        ### 4. OPERATIONAL CONSTRAINTS
        1.  **NO LOOPING (Within Request):** If you JUST called a tool (e.g., `list_emails`) for *this current request* and got results, do not call it again immediately. BUT, if this is a **NEW** user message or the user asks to "refresh" or "check again", you **MUST** call the tool again to get fresh data. Do NOT rely on old history for new requests.
        2.  **FORMATTING:** When presenting lists or links, ALWAYS use Markdown: `[Title](URL)`.
        3.  **DATA HANDLING:** If a tool returns a large JSON object, do not output the raw JSON. Summarize it (e.g., "I found 5 emails...").

        ### EXAMPLES (Few-Shot Learning)

        **User:** "Get me my last 3 important emails."
        **Reasoning:** User specified count (3) and filter (important).
        **Output:** {{ "tool": "list_emails", "arguments": {{ "limit": 3, "query": "is:important" }} }}

        **User:** "Summarize the last 10 emails from John."
        **Reasoning:** User wants content summary (not just list). Count is 10. Query is from:John.
        **Output:** {{ "tool": "get_recent_emails_content", "arguments": {{ "limit": 10, "query": "from:John" }} }}

        **User:** "Find all PDF files about 'Project X'."
        **Reasoning:** User said "all" (limit=100). Filter is PDF and name contains 'Project X'.
        **Output:** {{ "tool": "list_files", "arguments": {{ "limit": 100, "query": "name contains 'Project X' and mimeType = 'application/pdf'" }} }}

        **User:** "Send an email to boss@company.com saying I will be late."
        **Reasoning:** Writing request. Must draft first.
        **Output:** {{ "tool": "draft_email", "arguments": {{ "to": "boss@company.com", "subject": "Update on arrival", "body": "Hi,\n\nI will be late today.\n\nBest,\n[Name]" }} }}

        **User:** "Search for the latest iPhone rumors."
        **Reasoning:** Informational query.
        **Output:** {{ "tool": "search_web", "arguments": {{ "query": "latest iPhone rumors" }} }}

        ### RESPONSE FORMAT
        **CRITICAL INSTRUCTION**:
        If you need to use a tool, you must return **ONLY** a valid JSON object.
        **Do NOT** output any conversational text, reasoning, or markdown like "**Tool:**" before the JSON.
        
        **CORRECT FORMAT (JSON ONLY):**
        {{ "tool": "tool_name", "arguments": {{ "key": "value" }} }}

        **WRONG FORMAT (DO NOT USE):**
        "To satisfy this request I will use..."
        "**Tool:** list_emails"

        If you have the information to answer, respond in PLAIN TEXT.
    """)

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

    # 4. Inject Short-Term History
    recent_history = get_recent_history_text()
    
    current_context = f"{recent_history}{memory_context}User Request: {user_message}\n"
    final_response = ""
    last_intent = "chat"
    last_data = None
    
    # Track tools used in this turn
    tools_used_summary = []
    
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
                
                if tool_repetition_counts[current_tool_signature] > 1: # Strict: Block 2nd identical call.
                    print(f"DEBUG: Loop detected (>1 call). Identical tool call {tool_name}. Warning LLM.", file=sys.stderr)
                    current_context += f"\nSystem: You just called '{tool_name}' with these exact arguments and received results. **STOP**. Do not call it again. Summarize the results you already have.\n"
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
                        if tool_name.startswith("list_") or tool_name.startswith("read_") or tool_name.startswith("create_") or tool_name == "draft_email" or tool_name == "send_email" or tool_name == "get_recent_emails_content":
                             last_intent = tool_name
                             if tool_name == "list_upcoming_events": last_intent = "list_events" # normalize
                             if tool_name == "get_recent_emails_content": last_intent = "list_emails"
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
                    
                    tools_used_summary.append(f"{tool_name}: {display_output[:500]}...")
                    
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
        
    # Save to Short-Term History
    conversation_history.append({
        "user": user_message,
        "assistant": final_response,
        "tools": tools_used_summary
    })
    print(f"DEBUG: Conversation History Updated. Current Length: {len(conversation_history)}")
        
    return ChatResponse(
        response=final_response,
        intent=last_intent,
        data=last_data
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
