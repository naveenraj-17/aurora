import os
import sys
import json
import asyncio
import traceback
import time
print("🔥🔥🔥 SERVER.PY LOADED - VERSION WITH RAG DEBUGGING 🔥🔥🔥")
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import httpx
import boto3
from botocore.config import Config
from services.google import get_auth_url, finish_auth
from services.synthetic_data import generate_synthetic_data, SyntheticDataRequest, current_job, DATASETS_DIR

from services.n8n_sync import sync_global_config, fetch_global_config
from datetime import datetime
from core.personal_details import load_personal_details, save_personal_details
try:
    from core.memory import MemoryStore
except ImportError:
    print("Warning: MemoryStore dependencies not found. Memory disabled.")
    MemoryStore = None

from core.mcp_client import MCPClientManager

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
MAX_TURNS = 15  # Maximum ReAct loop iterations
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
    "sql": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "sql_agent.py"),
    "maps": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "map_details.py"),
    "personal_details": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "personal_details.py"),
    "collect_data": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "collect_data.py"),
    "pdf_parser": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "pdf_parser.py"),
    "xlsx_parser": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "xlsx_parser.py"),
}

class ChatRequest(BaseModel):
    message: str
    # Client-generated ID for scoping short-term context. Frontend should generate a new
    # one on each reload so each tab/reload is a fresh session.
    session_id: str | None = None
    # Optional ephemeral client-side state we want the server/agent to reuse.
    client_state: dict[str, Any] | None = None

class ChatResponse(BaseModel):
    response: str
    intent: str = "chat" # chat, list_emails, render_email, list_files, list_events, request_auth, list_local_files, render_local_file
    data: Any | None = None
    tool_name: str | None = None

# Global variables
# Map of client_name -> session
agent_sessions: dict[str, ClientSession] = {}
# Map of tool_name -> client_name
tool_router: dict[str, str] = {}
exit_stack = None
memory_store = None
mcp_manager: Optional[MCPClientManager] = None

from collections import deque

# Session-scoped short-term history/state. We intentionally do NOT persist these across reloads;
# the frontend should create a new session_id on page load.
conversation_histories: dict[str, deque] = {}
session_state: dict[str, dict[str, Any]] = {}

def _get_session_id(request: ChatRequest) -> str:
    return request.session_id or "default"

def _get_conversation_history(session_id: str) -> deque:
    if session_id not in conversation_histories:
        conversation_histories[session_id] = deque(maxlen=10)
    return conversation_histories[session_id]

def _get_session_state(session_id: str) -> dict[str, Any]:
    if session_id not in session_state:
        session_state[session_id] = {}
    return session_state[session_id]


def _apply_sticky_args(session_id: str, tool_name: str, tool_args: Any, tool_schema: dict | None = None) -> Any:
    """
    SIMPLIFIED Argument Persistence.
    
    Only injects client_state (URL params from frontend).
    Session context is provided via vector DB and system prompt injection.
    
    This prevents parameters from bleeding across different flows.
    Use clear_session_context tool to manage session lifecycle.
    """
    if not isinstance(tool_args, dict):
        tool_args = {}

    # Note: client_state is merged into session_state at request start (line ~1046)
    # We don't auto-inject from session_state here anymore
    # The LLM gets context via system prompt injection instead
    
    # Keep args in session for tracking (but don't auto-inject)
    ss = _get_session_state(session_id)
    for k, v in tool_args.items():
        if v and isinstance(v, (str, int, float, bool)):
            ss[k] = v

    return tool_args




def _clear_session_context(session_id: str, scope: str = "transient") -> list:
    """
    Clear session state based on scope.
    
    Scopes:
        - "transient": Clear flow-specific data (dimensions, IDs) but keep facility_id/location
        - "all": Clear everything
        - "ids_only": Clear only fields ending with _id
    
    Returns list of cleared keys.
    """
    ss = _get_session_state(session_id)
    cleared = []
    
    if scope == "all":
        cleared = list(ss.keys())
        ss.clear()
        print(f"DEBUG: Cleared ALL session context: {cleared}")
        
        # NEW: Clear session-scoped embeddings
        memory_store.clear_session_embeddings(session_id)
        cleared.append("session_embeddings")
        
    elif scope == "transient":
        # Clear everything except facility_id and location (persistent context)
        persistent = {"facility_id", "location"}
        to_remove = [k for k in ss.keys() if k not in persistent]
        for k in to_remove:
            del ss[k]
            cleared.append(k)
        print(f"DEBUG: Cleared TRANSIENT session context: {cleared}")
        
        # NEW: Also clear session embeddings on transient cleanup
        memory_store.clear_session_embeddings(session_id)
        cleared.append("session_embeddings")
        
    elif scope == "ids_only":
        # Clear only fields ending with _id or Id
        to_remove = [k for k in ss.keys() if k.endswith("_id") or k.endswith("Id")]
        for k in to_remove:
            del ss[k]
            cleared.append(k)
        print(f"DEBUG: Cleared ID fields from session context: {cleared}")
    else:
        print(f"DEBUG: Unknown scope '{scope}', no context cleared")
    
    return cleared


def _extract_and_persist_ids(session_id: str, tool_name: str, tool_output: str):
    """
    Extract IDs from tool output and persist to session state.
    ID-AGNOSTIC: Automatically detects any field ending with '_id' or 'Id'.
    Works for any agent/tool without hardcoded mappings.
    """
    try:
        parsed = json.loads(tool_output)
        
        ss = _get_session_state(session_id)
        
        def _extract_ids_recursive(data: Any, prefix: str = ""):
            """Recursively extract ID fields from nested dictionaries and lists."""
            
            if isinstance(data, dict):
                for key, value in data.items():
                    # Check if this looks like an ID field
                    is_id_field = (
                        key.endswith("_id") or 
                        key.endswith("Id") or 
                        key.lower() in ["id", "uuid"]
                    )
                    
                    if is_id_field and value is not None and value != "":
                        # Store with original key (not prefixed) for easy access
                        # We overwrite previous values, which effectively means "last seen ID wins"
                        ss[key] = value
                        print(f"DEBUG: Persisted {key}={value} to session state (from tool: {tool_name})")
                    
                    # Recurse into nested dicts
                    elif isinstance(value, (dict, list)):
                        _extract_ids_recursive(value, prefix=key)
            
            elif isinstance(data, list):
                # If list has items, verify they are dicts or lists
                # We prioritize the FIRST item for ID extraction if it's a single item list
                # Or if it's a list of results, the first result usually contains the relevant context ID
                if len(data) > 0:
                    # Strategy: Always extract from the FIRST item deeply
                    # This ensures if we get [Obj1, Obj2], we at least get Obj1's IDs.
                    # This matches "Single Item Array" requirement perfectly.
                    if isinstance(data[0], (dict, list)):
                         _extract_ids_recursive(data[0], prefix=f"{prefix}[0]")

        _extract_ids_recursive(parsed)
        
    except Exception as e:
        print(f"DEBUG: Could not extract IDs from tool output: {e}")

# System Prompt for Native Tool Calling (Enterprise/Business Focused)
NATIVE_TOOL_SYSTEM_PROMPT = """You are the Enterprise Business Intelligence Agent for a SaaS Platform.
Your mission is to assist managers, executives, and developers by retrieving accurate data, managing system operations, and explaining technical documentation.

### CURRENT DATE & TIME CONTEXT
**Current Date:** {current_date}
**Current Time:** {current_time}
**Timezone:** {timezone}

**IMPORTANT:** When tools return dates or timestamps, DO NOT add your own temporal context (e.g., "2 years from now", "next week"). Simply present the date/time returned by the tool. If you need to calculate relative time, use the appropriate tool or state the exact difference in days/weeks/months by doing simple math with the current date above.

### CORE OPERATING RULES
1.  **Think Step-by-Step:** Before calling a tool, briefly analyze the user's request. Determine if you need to fetch a list (IDs) before you can act on a specific item.
2.  **Accuracy First:** Never guess IDs (e.g., `item_123`, `email_999`). Always use `list_` or `search_` tools to find the real ID first.
3.  **Data Integrity:** When summarizing data (revenue, counts), be precise. Do not round numbers unless asked.
4.  **Security:** You are operating in a secure environment. You can access internal APIs and Databases via provided tools.

### TOOL USAGE PROTOCOL
*   **Listing vs. Acting:** If the user says "Email the last user", you MUST first call `list_users` or `get_recent_...` to get the email address. You cannot email a "concept".
*   **Parameters:**
    *   `limit`: Default to 5 unless specified (e.g., "all" -> 100).
    *   `query`: Convert natural language to search terms (e.g., "urgent" -> "is:urgent").
    *   **Geolocation:** If you have latitude/longitude from a previous tool (e.g., `get_facilities`), ALWAYS use `origin_lat`/`origin_lng` arguments instead of addresses. This avoids geocoding errors.

### TOOLS
You have access to the following tools:
{tools_json}

### RESPONSE STYLE
*   **Business Professional:** Be concise. No fluff.
*   **Action-Oriented:** If a task is done, say it. If data is retrieved, present it clearly (tables/lists).
"""

def get_recent_history_messages(session_id: str):
    """Returns a list of message dicts for the chat API."""
    messages = []
    for turn in _get_conversation_history(session_id):
        messages.append({"role": "user", "content": turn['user']})
        # If tools were used, we should ideally represent them, but for now 
        # let's represent the final assistant response to keep context usage expected.
        # Future improvement: Store full turn history including tool_calls and tool_outputs.
        messages.append({"role": "assistant", "content": turn['assistant']})
    return messages

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

        # --- Initialize External MCP Servers ---
        global mcp_manager
        mcp_manager = MCPClientManager(exit_stack)
        print("Connecting to external MCP servers...")
        external_sessions = await mcp_manager.connect_all()
        
        for name, session in external_sessions.items():
            # Prefix to avoid collision with internal agents
            agent_key = f"ext_mcp_{name}"
            agent_sessions[agent_key] = session
            print(f"Connected external MCP server: {name}")
            
            try:
                tools = await session.list_tools()
                print(f"  MCP Server '{name}' returned {len(tools.tools)} tools.")
                for tool in tools.tools:
                    tool_router[tool.name] = agent_key
                    print(f"  Registered external tool: {tool.name} -> {agent_key}")
            except Exception as e:
                print(f"  Error listing tools for {name}: {e}")
                import traceback
                traceback.print_exc()
                
        # Initialize Memory Store
        if MemoryStore:
            print("Initializing Memory Store...")
            global memory_store
            memory_store = _init_memory_store(load_settings())
        
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
from typing import Optional, Literal, Tuple
from urllib.parse import quote

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
USER_AGENTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "user_agents.json")
CUSTOM_TOOLS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "custom_tools.json")

# --- Custom Tools Management ---
def load_custom_tools():
    if not os.path.exists(CUSTOM_TOOLS_FILE):
        return []
    try:
        with open(CUSTOM_TOOLS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_custom_tools(tools):
    with open(CUSTOM_TOOLS_FILE, 'w') as f:
        json.dump(tools, f, indent=4)

@app.get("/api/tools/custom")
async def get_custom_tools():
    return load_custom_tools()

@app.get("/api/tools/available")
async def get_available_tools():
    """List all available tools from all sources (Native Agents, External MCP, Custom HTTP)"""
    all_tools = []
    
    # 1. Active MCP Sessions (Native + External)
    for name, session in agent_sessions.items():
        try:
            # Determine source type
            is_external = name.startswith("ext_mcp_")
            source_label = name.replace("ext_mcp_", "") if is_external else name
            tool_type = "mcp_external" if is_external else "mcp_native"
            
            # Fetch tools
            result = await session.list_tools()
            for t in result.tools:
                all_tools.append({
                    "name": t.name,
                    "description": t.description,
                    "source": source_label,
                    "type": tool_type,
                    "schema": t.inputSchema
                })
        except Exception as e:
            print(f"Error listing tools for agent '{name}': {e}")

    # 2. Custom HTTP Tools
    try:
        custom_tools = load_custom_tools()
        for t in custom_tools:
            all_tools.append({
                "name": t.get("name"),
                "label": t.get("generalName", t.get("name")), 
                "description": t.get("description", ""),
                "source": "custom_http",
                "type": "http",
                "schema": t.get("schema")
            })
    except Exception as e:
        print(f"Error listing custom tools: {e}")
        
    return {"tools": all_tools}

@app.post("/api/tools/custom")
async def create_custom_tool(tool: dict):
    # Expects: { id, name, description, method (GET/POST), url, schema }
    tools = load_custom_tools()
    # Check duplicate
    if any(t['name'] == tool['name'] for t in tools):
         # Update existing
         tools = [t if t['name'] != tool['name'] else tool for t in tools]
    else:
         tools.append(tool)
    save_custom_tools(tools)
    return {"status": "success", "tool": tool}

@app.delete("/api/tools/custom/{tool_name}")
async def delete_custom_tool(tool_name: str):
    tools = load_custom_tools()
    tools = [t for t in tools if t['name'] != tool_name]
    save_custom_tools(tools)
    return {"status": "success"}

# --- External MCP Server Management ---

@app.get("/api/mcp/servers")
async def list_mcp_servers():
    if not mcp_manager:
        return []
    return mcp_manager.servers_config

class AddMCPServerRequest(BaseModel):
    name: str
    command: str
    args: List[str] = []
    env: Dict[str, str] = {}

@app.post("/api/mcp/servers")
async def add_mcp_server(req: AddMCPServerRequest):
    if not mcp_manager:
        raise HTTPException(status_code=500, detail="MCP Manager not initialized")
    try:
        config = await mcp_manager.add_server(req.name, req.command, req.args, req.env)
        # Register the new session and tools immediately
        session = mcp_manager.sessions.get(req.name)
        if session:
             agent_key = f"ext_mcp_{req.name}"
             agent_sessions[agent_key] = session
             tools = await session.list_tools()
             for tool in tools.tools:
                 tool_router[tool.name] = agent_key
        return {"status": "success", "config": config}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/mcp/servers/{name}")
async def remove_mcp_server(name: str):
    if not mcp_manager:
        raise HTTPException(status_code=500, detail="MCP Manager not initialized")
    try:
        await mcp_manager.remove_server(name)
        # Cleanup session and router (best effort)
        agent_key = f"ext_mcp_{name}"
        if agent_key in agent_sessions:
            del agent_sessions[agent_key]
        # Cleanup router - expensive linear scan but infrequent
        keys_to_del = [k for k, v in tool_router.items() if v == agent_key]
        for k in keys_to_del:
            del tool_router[k]
            
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- Agent Management Logic ---
class Agent(BaseModel):
    id: str
    name: str
    description: str
    avatar: str = "default"
    type: str = "conversational"  # conversational | analysis | workflow
    tools: list[str] # ["all"] or ["gmail", "search_web"]
    system_prompt: str

class AgentActiveRequest(BaseModel):
    agent_id: str

active_agent_id = "aurora" # Default

def load_user_agents() -> list[dict]:
    if not os.path.exists(USER_AGENTS_FILE):
        return []
    try:
        with open(USER_AGENTS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_user_agents(agents: list[dict]):
    with open(USER_AGENTS_FILE, 'w') as f:
        json.dump(agents, f, indent=4)

def get_active_agent_data():
    agents = load_user_agents()
    for a in agents:
        if a["id"] == active_agent_id:
            return a
    # Fallback to first or hardcoded default if file empty
    if agents:
        return agents[0]
    return {
        "id": "aurora",
        "name": "Aurora",
        "system_prompt": NATIVE_TOOL_SYSTEM_PROMPT, # Fallback
        "tools": ["all"]
    }


class Settings(BaseModel):
    agent_name: str
    model: str = "mistral" # Default model (Ollama or Cloud)
    mode: str = "local" # "local" | "cloud" | "bedrock"
    openai_key: str = ""
    anthropic_key: str = ""
    gemini_key: str = ""
    google_maps_api_key: str = ""  # Google Maps Platform API key
    bedrock_api_key: str = ""  # e.g. ABSK... (Amazon Bedrock API key)
    # Optional: required for some Bedrock models that don't support on-demand throughput.
    # Can be an inference profile ID or full ARN.
    bedrock_inference_profile: str = ""
    # Optional: embedding model used for long-term memory when mode == bedrock
    embedding_model: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    aws_region: str = "us-east-1"
    sql_connection_string: str = ""
    n8n_url: str = "http://localhost:5678"
    n8n_api_key: str = ""
    n8n_table_id: str = ""
    global_config: dict[str, str] = {}
    show_browser: bool = False


class PersonalAddress(BaseModel):
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zipcode: str = ""


class PersonalDetails(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone_number: str = ""
    address: PersonalAddress = PersonalAddress()


class _MapsPoint(BaseModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class MapsDetailsRequest(BaseModel):
    # Accept either addresses or lat/lng (or mixed).
    origin_address: Optional[str] = None
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    destination_address: Optional[str] = None
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None
    travel_mode: Literal["driving", "walking", "bicycling", "transit"] = "driving"
    units: Literal["metric", "imperial"] = "metric"


def _normalize_point(address: Optional[str], lat: Optional[float], lng: Optional[float]) -> Tuple[str, dict]:
    """Return (distance-matrix-string, meta) or raise HTTPException for invalid input."""
    addr = (address or "").strip()
    has_coords = lat is not None and lng is not None
    if addr and has_coords:
        # Prefer coordinates for precise distance calculations.
        return f"{lat},{lng}", {"type": "latlng", "address": addr, "location": {"lat": lat, "lng": lng}}
    if has_coords:
        return f"{lat},{lng}", {"type": "latlng", "location": {"lat": lat, "lng": lng}}
    if addr:
        return addr, {"type": "address", "address": addr}
    raise HTTPException(status_code=422, detail="Both origin and destination must be provided as an address or as lat/lng.")


def _build_directions_url(origin: str, destination: str, travel_mode: str) -> str:
    # Google Maps Directions URL (works without an API key).
    # https://developers.google.com/maps/documentation/urls/get-started
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote(origin)}"
        f"&destination={quote(destination)}"
        f"&travelmode={quote(travel_mode)}"
    )


def _make_aws_client(service_name: str, region: str, settings: dict):
    """Create a boto3 client.

    If access/secret are not provided, boto3 will use its default credential chain
    (env vars, AWS_PROFILE, SSO, instance role, etc.).
    """
    # Amazon Bedrock API keys can be provided as a bearer token via this env var.
    # See: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html
    bedrock_api_key = (settings.get("bedrock_api_key") or "").strip()
    # Users often paste a full header value. Normalize to the raw ABSK... token.
    if bedrock_api_key:
        # Strip surrounding quotes
        if (bedrock_api_key.startswith('"') and bedrock_api_key.endswith('"')) or (
            bedrock_api_key.startswith("'") and bedrock_api_key.endswith("'")
        ):
            bedrock_api_key = bedrock_api_key[1:-1].strip()

        lower = bedrock_api_key.lower()
        if lower.startswith("authorization:"):
            bedrock_api_key = bedrock_api_key.split(":", 1)[1].strip()
            lower = bedrock_api_key.lower()
        if lower.startswith("bearer "):
            bedrock_api_key = bedrock_api_key.split(" ", 1)[1].strip()

    # If a Bedrock API key is provided, prefer it and avoid mixing auth mechanisms.
    if bedrock_api_key:
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bedrock_api_key
        access_key = ""
        secret_key = ""
        session_token = ""
    else:
        # Clear if user removed it in settings
        if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
            os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
        access_key = (settings.get("aws_access_key_id") or "").strip()
        secret_key = (settings.get("aws_secret_access_key") or "").strip()
        session_token = (settings.get("aws_session_token") or "").strip()
    region_name = (region or settings.get("aws_region") or "us-east-1").strip()

    kwargs = {
        "service_name": service_name,
        "region_name": region_name,
    }

    if access_key and secret_key:
        kwargs.update(
            {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
            }
        )
        if session_token:
            kwargs["aws_session_token"] = session_token

    # -------------------------------------------------------------------------
    # RETRY CONFIGURATION (Fix for ServiceUnavailableException / Throttling)
    # -------------------------------------------------------------------------
    # Standard retries are often insufficient for high-concurrency Bedrock usage.
    # Adaptive mode allows standard retry logic to dynamically adjust for
    # optimal request rates.
    retry_config = Config(
        retries={
            'max_attempts': 10,
            'mode': 'adaptive'
        },
        read_timeout=900,
        connect_timeout=900,
    )
    kwargs["config"] = retry_config

    return boto3.client(**kwargs)

def save_settings(settings: dict):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)


def _init_memory_store(settings: dict):
    """Initialize the long-term memory store with an embedding provider consistent with settings."""
    if not MemoryStore:
        return None

    mode = (settings.get("mode") or "local").strip().lower()
    model = (settings.get("model") or OLLAMA_MODEL).strip() or OLLAMA_MODEL

    # Default: Ollama embeddings (MemoryStore will handle it).
    embed_fn = None

    # Bedrock mode: use a Bedrock embedding model instead of Ollama.
    if mode == "bedrock":
        region = (settings.get("aws_region") or "us-east-1").strip() or "us-east-1"
        embed_model_id = (settings.get("embedding_model") or "amazon.titan-embed-text-v2:0").strip()

        def _bedrock_embed(text: str):
            bedrock = _make_aws_client("bedrock-runtime", region, settings)
            payload = {"inputText": text}
            resp = bedrock.invoke_model(
                modelId=embed_model_id,
                body=json.dumps(payload).encode("utf-8"),
                accept="application/json",
                contentType="application/json",
            )
            body = resp.get("body")
            data = json.loads(body.read()) if body else {}
            emb = data.get("embedding")
            return emb if isinstance(emb, list) else None

        embed_fn = _bedrock_embed

    return MemoryStore(model=model, embed_fn=embed_fn)

@app.get("/api/status")
async def get_status():
    # Helper to list agents from JSON
    user_agents = load_user_agents()
    agents_status = {}
    for a in user_agents:
        # For now, all loaded agents are "online" effectively
        agents_status[a["id"]] = {"name": a["name"], "status": "online"}
    
    current_settings = load_settings()
    
    return {
        "agents": agents_status, 
        "active_agent_id": active_agent_id,
        "overall": "operational", 
        "model": current_settings.get("model", "mistral"),
        "mode": current_settings.get("mode", "local")
    }

@app.get("/api/settings")
async def get_settings():
    settings = load_settings()
    # Attempt to fetch latest config from n8n (if connected)
    try:
        settings = await fetch_global_config(settings)
        # Optional: Save back to file to keep local cache updated?
        # save_settings(settings) 
    except Exception as e:
        print(f"Warning: Failed to fetch n8n config: {e}")
    return settings

@app.post("/api/settings")
async def update_settings(settings: Settings):
    print(f"DEBUG: update_settings called with: {settings.dict()}")
    data = settings.dict()

    
    # Sync with n8n if configured
    try:
        data = await sync_global_config(data)
    except Exception as e:
        print(f"Error syncing with n8n: {e}")
        # Proceed with saving even if sync fails
        
    save_settings(data)

    # Reinitialize memory so embeddings provider matches the new mode.
    global memory_store
    if MemoryStore:
        try:
            memory_store = _init_memory_store(data)
        except Exception as e:
            print(f"Warning: failed to reinitialize MemoryStore after settings update: {e}")
    return data


@app.get("/api/personal-details")
async def get_personal_details_api():
    return load_personal_details()


@app.post("/api/personal-details")
async def update_personal_details_api(details: PersonalDetails):
    data = details.dict()
    return save_personal_details(data)


@app.post("/api/maps/details")
async def get_maps_details(request: MapsDetailsRequest):
    """Compute distance and duration between two points using Google Distance Matrix API.

    Returns a structured JSON payload with distance, duration, and a Google Maps directions URL.
    """
    settings = load_settings()
    api_key = (settings.get("google_maps_api_key") or os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="google_maps_api_key is not configured")

    origin_str, origin_meta = _normalize_point(request.origin_address, request.origin_lat, request.origin_lng)
    dest_str, dest_meta = _normalize_point(request.destination_address, request.destination_lat, request.destination_lng)

    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin_str,
        "destinations": dest_str,
        "mode": request.travel_mode,
        "units": request.units,
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)

    # Distance Matrix returns JSON even on some errors.
    try:
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Google Maps API returned non-JSON response (status {resp.status_code})")

    api_status = data.get("status")
    if api_status != "OK":
        message = data.get("error_message") or api_status or "Unknown error"
        raise HTTPException(status_code=502, detail=f"Google Distance Matrix error: {message}")

    rows = data.get("rows") or []
    elements = (rows[0].get("elements") if rows and isinstance(rows[0], dict) else None) or []
    element = elements[0] if elements else {}
    element_status = element.get("status")
    if element_status != "OK":
        raise HTTPException(status_code=502, detail=f"No route found: {element_status}")

    distance = element.get("distance") or {}
    duration = element.get("duration") or {}
    distance_m = distance.get("value")
    duration_s = duration.get("value")

    directions_url = _build_directions_url(origin_str, dest_str, request.travel_mode)

    return {
        "provider": "google_distance_matrix",
        "travel_mode": request.travel_mode,
        "units": request.units,
        "origin": origin_meta,
        "destination": dest_meta,
        "distance": {
            "meters": distance_m,
            "kilometers": (distance_m / 1000.0) if isinstance(distance_m, (int, float)) else None,
            "text": distance.get("text"),
        },
        "duration": {
            "seconds": duration_s,
            "minutes": (duration_s / 60.0) if isinstance(duration_s, (int, float)) else None,
            "text": duration.get("text"),
        },
        "directions_url": directions_url,
    }


# --- n8n Integration (server-side proxy) ---
def _get_n8n_config():
    settings = load_settings()
    base_url = (settings.get("n8n_url") or "").strip()
    api_key = (settings.get("n8n_api_key") or "").strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="n8n_url is not configured")
    if not api_key:
        raise HTTPException(status_code=400, detail="n8n_api_key is not configured")
    return base_url.rstrip("/"), api_key


async def _n8n_request(method: str, path: str):
    base_url, api_key = _get_n8n_config()
    url = f"{base_url}{path}"
    headers = {"X-N8N-API-KEY": api_key}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method, url, headers=headers)
            if resp.status_code in (401, 403):
                raise HTTPException(status_code=401, detail="n8n authentication failed")
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"n8n request failed: {str(e)}")


@app.get("/api/n8n/workflows")
async def n8n_list_workflows():
    """Lists workflows from n8n (requires n8n_url + n8n_api_key in settings)."""
    data = await _n8n_request("GET", "/api/v1/workflows")

    workflows = []
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        workflows = data.get("data")
    elif isinstance(data, list):
        workflows = data

    # Normalize to a minimal UI-friendly shape
    return [
        {
            "id": str(w.get("id")) if w.get("id") is not None else "",
            "name": w.get("name") or "",
            "active": bool(w.get("active")) if w.get("active") is not None else False,
            "updatedAt": w.get("updatedAt") or w.get("updated_at") or None,
        }
        for w in workflows
        if w is not None
    ]


@app.get("/api/n8n/workflows/{workflow_id}/webhook")
async def n8n_get_workflow_webhook(workflow_id: str):
    """Derives the production webhook URL for a workflow by locating a Webhook trigger node."""
    base_url, _ = _get_n8n_config()
    workflow = await _n8n_request("GET", f"/api/v1/workflows/{workflow_id}")

    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    if not isinstance(nodes, list):
        raise HTTPException(status_code=404, detail="Workflow nodes not found")

    webhook_node = None
    # Prefer the canonical webhook node type
    for node in nodes:
        if isinstance(node, dict) and (node.get("type") == "n8n-nodes-base.webhook"):
            webhook_node = node
            break
    # Fallback: any node containing 'webhook'
    if webhook_node is None:
        for node in nodes:
            t = (node.get("type") or "") if isinstance(node, dict) else ""
            if "webhook" in t.lower():
                webhook_node = node
                break

    if webhook_node is None:
        raise HTTPException(status_code=404, detail="No webhook trigger node found in workflow")

    parameters = webhook_node.get("parameters") if isinstance(webhook_node, dict) else None
    path = parameters.get("path") if isinstance(parameters, dict) else None
    if not path or not isinstance(path, str):
        raise HTTPException(status_code=404, detail="Webhook path not found in workflow")

    clean_path = path.lstrip("/")
    production_url = f"{base_url}/webhook/{clean_path}"
    return {"workflowId": str(workflow_id), "path": clean_path, "productionUrl": production_url}

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



# --- Agent Endpoints ---
@app.get("/api/agents")
async def get_agents():
    return load_user_agents()

@app.post("/api/agents")
async def create_agent(agent: Agent):
    agents = load_user_agents()
    # Check if exists
    for i, a in enumerate(agents):
        if a["id"] == agent.id:
            agents[i] = agent.dict() # Update
            save_user_agents(agents)
            return agent
    
    agents.append(agent.dict())
    save_user_agents(agents)
    return agent

@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if agent_id == "aurora":
         raise HTTPException(status_code=400, detail="Cannot delete default agent.")
    agents = load_user_agents()
    agents = [a for a in agents if a["id"] != agent_id]
    save_user_agents(agents)
    return {"status": "success"}

@app.get("/api/agents/active")
async def get_active_agent_endpoint():
    return {"active_agent_id": active_agent_id}

@app.post("/api/agents/active")
async def set_active_agent_endpoint(req: AgentActiveRequest):
    global active_agent_id
    # Validate
    agents = load_user_agents()
    ids = [a["id"] for a in agents]
    if req.agent_id not in ids:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    active_agent_id = req.agent_id
    print(f"Active Agent switched to: {active_agent_id}")
    return {"status": "success", "active_agent_id": active_agent_id}

# --- Synthetic Data Endpoints ---
@app.post("/api/synthetic/generate")
async def start_synthetic_generation(req: SyntheticDataRequest):
    if current_job["status"] == "generating":
        raise HTTPException(status_code=400, detail="A generation job is already running.")
    
    # Run in background
    asyncio.create_task(generate_synthetic_data(req))
    return {"status": "started", "message": "Generation started in background."}

@app.get("/api/synthetic/status")
async def get_synthetic_status():
    return current_job

@app.get("/api/synthetic/datasets")
async def list_datasets():
    if not os.path.exists(DATASETS_DIR):
        return []
    files = [f for f in os.listdir(DATASETS_DIR) if f.endswith(".jsonl")]
    # Return list of {filename, size, date}
    results = []
    for f in files:
        path = os.path.join(DATASETS_DIR, f)
        stats = os.stat(path)
        results.append({
            "filename": f,
            "size": stats.st_size,
            "created": datetime.fromtimestamp(stats.st_ctime).isoformat()
        })
    return sorted(results, key=lambda x: x["created"], reverse=True)

@app.get("/api/models")
async def get_models():
    """Fetches available models from Ollama + Cloud Options."""
    cloud_models = [
        "gpt-4o", "gpt-4-turbo", 
        "claude-3-5-sonnet", 
        "gemini-3-pro-preview", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash",
        "bedrock.anthropic.claude-3-5-sonnet-20240620-v1:0",
        "bedrock.anthropic.claude-3-sonnet-20240229-v1:0"
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


@app.get("/api/bedrock/models")
async def get_bedrock_models():
    """Lists Bedrock foundation models.

    Note: This requires AWS credentials with `bedrock:ListFoundationModels`.
    If no explicit keys are provided, the server will rely on boto3's default
    credential chain (AWS_PROFILE/SSO/env/instance role).
    """
    settings = load_settings()
    region = (settings.get("aws_region") or "us-east-1").strip() or "us-east-1"

    def _list_models_sync():
        client = _make_aws_client("bedrock", region, settings)
        resp = client.list_foundation_models()
        summaries = resp.get("modelSummaries", []) or []
        models: list[str] = []
        for s in summaries:
            model_id = s.get("modelId")
            if model_id:
                models.append(f"bedrock.{model_id}")
        return sorted(set(models))

    try:
        models = await asyncio.to_thread(_list_models_sync)
        return {"models": models}
    except Exception as e:
        # Keep error details out of the client response; log server-side.
        print(f"Error listing Bedrock models: {e}")
        return {
            "models": [],
            "error": "Unable to list Bedrock models. Check AWS credentials/permissions and region.",
        }


@app.get("/api/bedrock/inference-profiles")
async def get_bedrock_inference_profiles():
    """Lists Bedrock inference profiles.

    Some Bedrock models do not support on-demand throughput and must be invoked
    using an inference profile ID/ARN. This endpoint helps the UI present
    selectable inference profiles.
    """
    settings = load_settings()
    region = (settings.get("aws_region") or "us-east-1").strip() or "us-east-1"

    def _list_profiles_sync():
        client = _make_aws_client("bedrock", region, settings)

        if not hasattr(client, "list_inference_profiles"):
            return []

        resp = client.list_inference_profiles()
        # Boto3 uses 'inferenceProfileSummaries' as of current API shape.
        summaries = (
            resp.get("inferenceProfileSummaries")
            or resp.get("inferenceProfiles")
            or resp.get("summaries")
            or []
        )
        profiles = []
        for s in summaries or []:
            if not isinstance(s, dict):
                continue
            profiles.append(
                {
                    "id": s.get("inferenceProfileId") or s.get("id") or "",
                    "arn": s.get("inferenceProfileArn") or s.get("arn") or "",
                    "name": s.get("inferenceProfileName") or s.get("name") or "",
                    "status": s.get("status") or "",
                }
            )
        # Prefer stable ordering for UI.
        return sorted(profiles, key=lambda p: (p.get("name") or p.get("arn") or p.get("id") or ""))

    try:
        profiles = await asyncio.to_thread(_list_profiles_sync)
        return {"profiles": profiles}
    except Exception as e:
        print(f"Error listing Bedrock inference profiles: {e}")
        return {
            "profiles": [],
            "error": "Unable to list Bedrock inference profiles. Check AWS credentials/permissions and region.",
        }

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
    conversation_histories.clear()
    session_state.clear()
    return {"status": "success", "message": "Recent session history (all sessions) cleared."}

@app.delete("/api/history/all")
async def clear_all_history():
    """Clears BOTH short-term session history AND long-term ChromaDB memory."""
    conversation_histories.clear()
    session_state.clear()
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

    session_id = _get_session_id(request)
    user_message = request.message

    # Merge client-provided ephemeral state into server session state (best-effort)
    ss = _get_session_state(session_id)
    if request.client_state and isinstance(request.client_state, dict):
        active_facility = request.client_state.get("active_facility_id")
        if active_facility:
            ss["facility_id"] = str(active_facility)
    
    # 1. Aggregate Tools & Build Schema Map
    all_tools = []
    tool_schema_map = {} # name -> inputSchema
    
    # -- Load Active Agent Logic --
    active_agent = get_active_agent_data()
    allowed_tools = active_agent.get("tools", ["all"])
    agent_system_template = active_agent.get("system_prompt", NATIVE_TOOL_SYSTEM_PROMPT)
    
    print(f"DEBUG: Using Agent '{active_agent.get('name')}' with tools: {allowed_tools}")

    # Standard MCP Tools
    for session in agent_sessions.values():
        result = await session.list_tools()
        if "all" in allowed_tools:
            all_tools.extend(result.tools)
        else:
            for t in result.tools:
                if t.name in allowed_tools:
                    all_tools.extend([t])

    # Populate schema map for MCP tools
    for t in all_tools:
        tool_schema_map[t.name] = t.inputSchema

    # Dynamic Custom Tools (n8n/Webhook)
    custom_tools = load_custom_tools()
    # We map custom tools to a simplified object that looks like an MCP tool
    class VirtualTool:
        def __init__(self, name, description, inputSchema):
            self.name = name
            self.description = description
            self.inputSchema = inputSchema

    # ========================================================================
    # VIRTUAL TOOLS: Session & Context Management (ALWAYS AVAILABLE)
    # ========================================================================
    # These tools are INFRASTRUCTURE-level and available to ALL agents,
    # regardless of the 'tools' array in user_agents.json.
    # 
    # Rationale:
    # - Session management is like memory management - every agent needs it
    # - Prevents cross-flow parameter contamination universally
    # - Simplifies agent configuration (no need to remember to add these)
    #
    # Tools in this category:
    # - query_past_conversations: Long-term memory retrieval
    # - get_current_session_context: Access session state
    # - clear_session_context: Reset session for new flows
    # ========================================================================

    # Internal tool: on-demand long-term memory retrieval (instead of injecting memory by default)
    mem_tool = VirtualTool(
            "query_past_conversations",
            "Search long-term conversation memory. Use this only when you need context from older sessions."
            " Arguments: query (string), n_results (int, optional), scope ('all'|'session').",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "n_results": {"type": "integer", "default": 5},
                    "scope": {"type": "string", "enum": ["all", "session"], "default": "all"},
                },
                "required": ["query"],
            },
        )
    all_tools.append(mem_tool)
    tool_schema_map[mem_tool.name] = mem_tool.inputSchema

    # Internal tool: Current Session Context (New!)
    context_tool = VirtualTool(
        "get_current_session_context",
        "Get valid IDs (facility_id, etc.) and location from the current active session state.",
        {
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    all_tools.append(context_tool)
    tool_schema_map[context_tool.name] = context_tool.inputSchema

    # Internal tool: Clear Session Context
    clear_context_tool = VirtualTool(
        "clear_session_context",
        "Clear session state to start a fresh flow. Call this when you detect the user wants to start a NEW reservation "
        "or operation (e.g., 'I need another space', 'different size', 'start over'). "
        "Scope: 'transient' (default - clear IDs but keep facility/location), 'all' (clear everything), 'ids_only' (clear only ID fields).",
        {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["transient", "all", "ids_only"],
                    "default": "transient",
                    "description": "transient: Clear flow-specific data. all: Clear everything. ids_only: Clear only _id fields."
                }
            },
            "required": []
        }
    )
    all_tools.append(clear_context_tool)
    tool_schema_map[clear_context_tool.name] = clear_context_tool.inputSchema
    
    # RAG Decision and Search Tools (for report data)
    decide_tool = VirtualTool(
        "decide_search_or_analyze",
        "**INTERNAL**: Decide whether to search embeddings or directly analyze report data. "
        "Report data is ALREADY embedded after execution - this just determines the approach. "
        "\n\n**Use search_embedded_report when:**"
        "\n- Vague queries: 'concerning patterns', 'unusual behavior'"
        "\n- Correlation: 'users with most issues', 'similar items'"
        "\n- Large reports (>100 rows) with open-ended questions"
        "\n\n**Use direct analysis when:**"
        "\n- Specific: 'How many?', 'Show Roland', 'Total balance'"
        "\n- Counting/filtering/summarization"
        "\n\n**Note:** Report is already in current context AND embedded. Choose fastest approach.",
        {
            "type": "object",
            "properties": {
                "user_query": {"type": "string", "description": "The user's question about the report"},
                "report_size": {"type": "integer", "description": "Number of rows in the report"},
                "query_type": {"type": "string", "enum": ["exploratory", "specific"], "description": "Query classification"}
            },
            "required": ["user_query", "report_size"]
        }
    )
    all_tools.append(decide_tool)
    tool_schema_map[decide_tool.name] = decide_tool.inputSchema
    
    # Expose search tool for embedded reports
    search_tool = VirtualTool(
        "search_embedded_report",
        "Search the automatically-embedded report data semantically. Use for vague/exploratory queries about report patterns.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "n_results": {"type": "integer", "default": 3, "description": "Max chunks to return"}
            },
            "required": ["query"]
        }
    )
    all_tools.append(search_tool)
    tool_schema_map[search_tool.name] = search_tool.inputSchema
    
    for ct in custom_tools:
        # If 'all' or explicitly listed
        if "all" in allowed_tools or ct['name'] in allowed_tools:
             vt = VirtualTool(ct['name'], ct['description'], ct['inputSchema'])
             all_tools.append(vt)
             tool_schema_map[vt.name] = vt.inputSchema

    # 2. System Prompt
    # Prepare tools for Ollama Native API (List of dicts)
    ollama_tools = [{'type': 'function', 'function': {'name': t.name, 'description': t.description, 'parameters': t.inputSchema}} for t in all_tools]
    
    # Keep the string version for Cloud models (System Prompt injection)
    tools_json = str([{'name': t.name, 'description': t.description, 'schema': t.inputSchema} for t in all_tools])
    
    TOOL_USAGE_INSTRUCTION = """
    
    ### CURRENT DATE & TIME CONTEXT
    **Current Date:** {current_date}
    **Current Time:** {current_time}
    **Timezone:** {timezone}
    
    **IMPORTANT:** When tools return dates or timestamps, DO NOT add your own temporal context. Simply present the date/time returned by the tool.
    
    ### RESPONSE FORMAT INSTRUCTIONS
    If you need to use a specific tool from the list above, you MUST respond with **ONLY** a valid JSON object in the following format:
    { "tool": "tool_name", "arguments": { "key": "value" } }
    
    Do NOT output any other text or markdown when calling a tool.
    If you do not need to use a tool, reply in plain text.
    """
    
    # Get current date/time for context injection
    from datetime import datetime
    import zoneinfo
    now = datetime.now(zoneinfo.ZoneInfo("UTC"))
    current_date = now.strftime("%B %d, %Y")  # e.g., "February 11, 2026"
    current_time = now.strftime("%I:%M %p")   # e.g., "03:30 PM"
    timezone = "UTC"
    
    # Inject tools, date/time, and instructions into the template
    system_prompt_text = agent_system_template.replace("{tools_json}", tools_json + TOOL_USAGE_INSTRUCTION)
    system_prompt_text = system_prompt_text.replace("{current_date}", current_date)
    system_prompt_text = system_prompt_text.replace("{current_time}", current_time)
    system_prompt_text = system_prompt_text.replace("{timezone}", timezone)


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
            data = resp.json()
            
            if not data.get("candidates"):
                return "Error: No response candidates from Gemini."
            
            candidate = data["candidates"][0]
            if candidate.get("finishReason") == "SAFETY":
                 return "Error: Response blocked by Gemini safety filters."
            
            if not candidate.get("content") or not candidate["content"].get("parts"):
                 return f"Error: Malformed Gemini response. Finish Reason: {candidate.get('finishReason')}"

            return candidate["content"]["parts"][0]["text"]

    async def call_bedrock(model_id, messages, system, region, settings):
        # Bedrock requires the exact model ID (e.g., anthropic.claude-3-5-sonnet-20240620-v1:0)
        # We strip the 'bedrock.' prefix if present
        real_model_id = model_id.replace("bedrock.", "")

        # Some Bedrock models require an inference profile (no on-demand throughput).
        # If provided, we invoke using the inference profile ID/ARN as modelId.
        invocation_model_id = real_model_id
        inference_profile = (settings.get("bedrock_inference_profile") or "").strip()
        if inference_profile:
            # Users may paste it with a bedrock. prefix from the UI list.
            if inference_profile.startswith("bedrock."):
                inference_profile = inference_profile.replace("bedrock.", "", 1)
            invocation_model_id = inference_profile
        
        # Convert messages to Bedrock Converse API format or InvokeModel
        # Using Converse API (standardized) is preferred for newer models
        
        bedrock = _make_aws_client("bedrock-runtime", region, settings)

        # Normalize messages to a content-block list.
        # For Bedrock Converse, content blocks are like: {"text": "..."}
        # For Anthropic InvokeModel, blocks are like: {"type": "text", "text": "..."}
        normalized_messages = []
        for m in (messages or []):
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            content = m.get("content")
            if isinstance(content, str):
                normalized_messages.append({"role": role, "content": [{"text": content}]})
            elif isinstance(content, list):
                # Best effort: if caller already provided blocks, keep them but coerce to Converse schema
                blocks = []
                for b in content:
                    if isinstance(b, dict) and "text" in b:
                        blocks.append({"text": str(b.get("text"))})
                    elif isinstance(b, dict) and b.get("type") == "text" and "text" in b:
                        blocks.append({"text": str(b.get("text"))})
                    else:
                        blocks.append({"text": str(b)})
                normalized_messages.append({"role": role, "content": blocks})
            else:
                normalized_messages.append({"role": role, "content": [{"text": str(content)}]})

        system_blocks = []
        if system and str(system).strip():
            system_blocks = [{"text": str(system)}]

        async def _converse_call():
            def _run():
                return bedrock.converse(
                    modelId=invocation_model_id,
                    messages=normalized_messages,
                    system=system_blocks,
                    inferenceConfig={"maxTokens": 4096},
                )

            return await asyncio.to_thread(_run)

        async def _invoke_model_call():
            # InvokeModel using Anthropic Messages schema
            anthropic_messages = []
            for m in normalized_messages:
                anthropic_messages.append(
                    {
                        "role": m["role"],
                        "content": [{"type": "text", "text": b.get("text", "")} for b in (m.get("content") or [])],
                    }
                )

            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "system": str(system or ""),
                "messages": anthropic_messages,
            }

            def _run():
                return bedrock.invoke_model(
                    body=json.dumps(payload).encode("utf-8"),
                    modelId=invocation_model_id,
                    accept="application/json",
                    contentType="application/json",
                )

            return await asyncio.to_thread(_run)

        # Prefer Converse if available; it avoids many per-model JSON schema mismatches.
        try:
            if hasattr(bedrock, "converse"):
                resp = await _converse_call()
                msg = (((resp or {}).get("output") or {}).get("message") or {})
                content = msg.get("content") or []
                if content and isinstance(content, list) and isinstance(content[0], dict):
                    return content[0].get("text", "")
                return ""
        except Exception as e:
            message = str(e)
            if "on-demand throughput isn’t supported" in message or "on-demand throughput isn't supported" in message:
                raise RuntimeError(
                    "Bedrock model requires an inference profile (no on-demand throughput). "
                    "Set settings.bedrock_inference_profile to an inference profile ID/ARN that includes this model, "
                    "or pick a different Bedrock model that supports on-demand throughput."
                )
            # Fall back to InvokeModel; keep original exception in server logs.
            print(f"Bedrock converse failed, falling back to invoke_model: {e}")

        try:
            resp = await _invoke_model_call()
            response_body = json.loads(resp.get("body").read()) if resp and resp.get("body") else {}
            content = response_body.get("content") or []
            if content and isinstance(content, list) and isinstance(content[0], dict):
                return content[0].get("text", "")
            return ""
        except Exception as e:
            message = str(e)
            if "on-demand throughput isn’t supported" in message or "on-demand throughput isn't supported" in message:
                raise RuntimeError(
                    "Bedrock model requires an inference profile (no on-demand throughput). "
                    "Set settings.bedrock_inference_profile to an inference profile ID/ARN that includes this model, "
                    "or pick a different Bedrock model that supports on-demand throughput."
                )
            raise

    def _messages_to_transcript(messages: list[dict] | None) -> str:
        """Lossy conversion of role/content messages to plain text for providers that only accept a single prompt."""
        if not messages:
            return ""
        lines: list[str] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = (m.get("role") or "").strip().lower()
            content = m.get("content")
            if isinstance(content, list):
                # Best-effort concatenate any text blocks
                parts: list[str] = []
                for p in content:
                    if isinstance(p, dict) and isinstance(p.get("text"), str):
                        parts.append(p["text"])
                text = "\n".join(parts).strip()
            else:
                text = (content or "").strip() if isinstance(content, str) else ""

            if not text:
                continue

            if role == "user":
                label = "User"
            elif role == "assistant":
                label = "Assistant"
            elif role:
                label = role.title()
            else:
                label = "Message"
            lines.append(f"{label}: {text}")
        return "\n".join(lines)

    async def generate_response(
        prompt_msg,
        sys_prompt,
        tools=None,
        history_messages=None,
        memory_context_text: str = "",
    ):
        augmented_system = (sys_prompt or "").strip()
        if memory_context_text and memory_context_text.strip():
            augmented_system = f"{augmented_system}\n\n{memory_context_text.strip()}".strip()

        if mode in ["cloud", "bedrock"]:
            try:
                # Construct messages list for cloud providers that support it
                messages = []
                if history_messages:
                    messages.extend(history_messages)
                messages.append({"role": "user", "content": prompt_msg})

                if current_model.startswith("gpt"):
                    return await call_openai(
                        current_model,
                        [{"role": "system", "content": augmented_system}] + messages,
                        current_settings.get("openai_key"),
                    )
                elif current_model.startswith("claude"):
                    return await call_anthropic(
                        current_model,
                        messages,
                        augmented_system,
                        current_settings.get("anthropic_key"),
                    )
                elif current_model.startswith("gemini"):
                    # Gemini wrapper currently only accepts a single prompt string.
                    transcript = _messages_to_transcript(messages)
                    return await call_gemini(
                        current_model,
                        transcript or str(prompt_msg),
                        augmented_system,
                        current_settings.get("gemini_key"),
                    )
                elif current_model.startswith("bedrock"):
                    return await call_bedrock(
                        current_model,
                        messages,
                        augmented_system,
                        current_settings.get("aws_region"),
                        current_settings,
                    )
                else:
                    return "Error: Unknown cloud model selected."
            except Exception as e:
                return f"Cloud API Error: {str(e)}"
        
        # Local Ollama
        async with httpx.AsyncClient() as client:
            try:
                # Try specific Ollama Tool Call format if tools are provided
                if tools:
                    print(f"DEBUG: Calling Ollama /api/chat with tools...", flush=True)
                    
                    # Construct full message history
                    # 1. System Prompt
                    messages = [{"role": "system", "content": augmented_system}]
                    
                    # 2. History (if available)
                    if history_messages:
                        messages.extend(history_messages)
                        
                    # 3. Current User Message
                    messages.append({"role": "user", "content": prompt_msg})

                    response = await client.post(
                        f"{OLLAMA_BASE_URL}/api/chat",
                        json={
                            "model": current_model,
                            "messages": messages,
                            "tools": tools,
                            "stream": False
                        },
                        timeout=None
                    )
                    response.raise_for_status()
                    data = response.json()
                    msg = data.get("message", {})
                    
                    # Check for native tool calls
                    if "tool_calls" in msg and msg["tool_calls"]:
                        # Convert Ollama native tool call to our internal JSON format
                        tc = msg["tool_calls"][0]
                        print(f"DEBUG: Native Tool Call received: {tc['function']['name']}", flush=True)
                        return json.dumps({
                            "tool": tc["function"]["name"], 
                            "arguments": tc["function"]["arguments"]
                        })
                    
                    return msg.get("content", "")

                # Fallback to generate if no tools or tools failed (Old behavior)
                print(f"DEBUG: Calling Ollama /api/generate (Legacy Mode)...", flush=True)

                prompt_for_generate = prompt_msg
                if history_messages:
                    prior = _messages_to_transcript(history_messages)
                    if prior:
                        prompt_for_generate = f"Conversation so far:\n{prior}\n\nUser: {prompt_msg}".strip()

                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": current_model,
                        "prompt": prompt_for_generate,
                        "system": augmented_system,
                        "stream": False
                    },
                    timeout=None
                )
                response.raise_for_status()
                return response.json().get("response", "")
            except Exception as e:
                return f"Local Agent Error: {e}"

    # --- ReAct Loop ---
    
    # 3. Retrieve Memory
    # IMPORTANT: Do not query long-term memory by default. This keeps requests fast and keeps
    # context scoped to the current session unless the model explicitly asks to retrieve it.
    memory_context = ""

    # 4. Inject Short-Term History
    # 4. Inject Short-Term History
    recent_history_messages = get_recent_history_messages(session_id)
    
    # Context for LLM (Text-based Fallback for non-native logic or logging)
    # We still keep a text version for "current_context" used in loop logic if needed, 
    # but the API call will use the structured messages.
    
    # current_context is mainly strictly for the 'legacy/text' based prompt construction if we fell back,
    # OR for the internal logic loop to append tool outputs.
    # For the INITIAL prompt, we use the user_message.
    
    current_context_text = f"User Request: {user_message}\n" 

    # --- INJECT SESSION CONTEXT ---
    # Retrieve current session state to inject into the prompt
    # This ensures the model implicitly knows "active_facility_id" without asking.
    active_ss = _get_session_state(session_id)
    if active_ss:
        # Filter out empty values
        valid_context = {k: v for k, v in active_ss.items() if v}
        if valid_context:
            context_str = json.dumps(valid_context, indent=2)
            # We append this to the system prompt or user prompt so the model sees it.
            # Appending to system prompt is safer to avoid confusing the user message history.
            system_prompt_text += f"\n\n### CURRENT SESSION CONTEXT ###\nThe following variables are active in the current session. You can use these values for tool arguments (e.g., facility_id) without asking the user:\n{context_str}\n"
    
    # --- INJECT RECENT TOOL OUTPUTS ---
    # This provides the LLM with a summary of recently executed tools and their outputs,
    # especially useful for multi-request flows (e.g., hold_space → collect_data → reserve_space)
    if memory_store:
        try:
            recent_tools = memory_store.get_session_tool_outputs(
                session_id=session_id,
                n_results=5
            )
            
            if recent_tools and recent_tools.get('documents'):
                tools_summary = "\n".join([
                    f"- {doc}" 
                    for doc in recent_tools['documents']
                ])
                
                system_prompt_text += f"""

### RECENT TOOL EXECUTIONS ###
The following tools were executed recently in this session. Use the output values (especially IDs) from these tools:
{tools_summary}

### SESSION LIFECYCLE MANAGEMENT ###
When you detect the user wants to start a NEW operation or flow, call clear_session_context() BEFORE calling other tools:

Examples:
- User: "Now I need a parking space" (after climate) → clear_session_context(scope="transient")
- User: "Different size" → clear_session_context(scope="ids_only")  
- User: "Start over" → clear_session_context(scope="all")
"""
        except Exception as e:
            print(f"DEBUG: Error injecting tool history: {e}")
 
    
    final_response = ""
    last_intent = "chat"
    last_data = None
    tool_name = None
    
    # Track tools used in this turn
    tools_used_summary = []
    
    print(f"--- Starting ReAct Loop for: {user_message} ---")
    last_tool_signature = ""
    tool_repetition_counts = {}

    tool_repetition_counts = {}

    async with httpx.AsyncClient() as client:
        for turn in range(MAX_TURNS):
            print(f"Turn {turn + 1}/{MAX_TURNS}")
            
            # Determine Prompt logic
            # If it's the first turn, we use the clean Native System Prompt & History
            if turn == 0:
                 active_sys_prompt = system_prompt_text
                 # We simply pass the user message. The 'generate_response' will prepend history.
                 active_prompt = user_message 
                 active_history = recent_history_messages
            else:
                 # Successive turns in the ReAct loop (Tool outputs)
                 # We must append the tool output to the message chain effectively.
                 # For simplicity in this hybrid setup, we'll append to the 'user' prompt side 
                 # because constructing a valid multi-turn tool-call history for Ollama manually is complex 
                 # without storing the specific tool_call_id etc.
                 
                 # Using the 'Legacy' text-injection style for immediate tool feedback works robustly 
                 # because the model sees "Tool Output: ..." as user text context.
                 active_sys_prompt = system_prompt_text # Keep it simple
                 active_prompt = current_context_text # Contains accumulated tool outputs
                 active_history = [] # Don't duplicate history in the context frame repeatedly if we are just continuing the thought
            
            # Ask LLM
            llm_output = await generate_response(
                active_prompt, 
                active_sys_prompt, 
                tools=ollama_tools, 
                history_messages=active_history,
                memory_context_text=memory_context,
            )
            print(f"DEBUG: LLM Output: {llm_output[:100]}...") # Log first 100 chars
            
            # Parse Tool Call
            import re
            tool_call = None
            json_error = None
            
            try:
                cleaned_output = llm_output.replace("```json", "").replace("```", "").strip()
                
                # 1. Try direct JSON parsing (Native tool call returns pure JSON)
                try:
                    tool_call = json.loads(cleaned_output)
                except:
                    # 2. Try Regex Extraction (Manual ReAct fallback)
                    json_match = re.search(r'\{.*\}', cleaned_output, re.DOTALL)
                    if json_match:
                        tool_call = json.loads(json_match.group(0))
            except Exception as e:
                json_error = str(e)

            if json_error:
                print(f"DEBUG: JSON Error: {json_error}")
                current_context_text += f"\nSystem: JSON Parsing Error: {json_error}. You generated invalid JSON (likely unescaped quotes or newlines). Please Try Again with valid, escaped JSON.\n"
                continue

            if tool_call and isinstance(tool_call, dict) and "tool" in tool_call:
                # It's a tool call!
                tool_name = tool_call["tool"]
                tool_args = tool_call.get("arguments", {})
                
                # Apply Sticky Args (Facility ID, Location, etc.)
                tool_schema = tool_schema_map.get(tool_name)
                tool_args = _apply_sticky_args(session_id, tool_name, tool_args, tool_schema)
                
                print(f"DEBUG: EXTRACTED TOOL ARGS: {tool_name} -> {tool_args}")

                # --- UNIVERSAL LOOP GUARD ---
                current_tool_signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                tool_repetition_counts[current_tool_signature] = tool_repetition_counts.get(current_tool_signature, 0) + 1
                
                if tool_repetition_counts[current_tool_signature] > 1:
                    print(f"DEBUG: Loop detected (>1 call). Identical tool call {tool_name}. Blocking.", file=sys.stderr)
                    current_context_text += f"\nSystem: You just called '{tool_name}' with these exact arguments and received results. **STOP**. Do not call it again within this request. Summarize the results you already have.\n"
                    continue
                
                last_tool_signature = current_tool_signature

                # 1. Internal Tool: Session Context
                if tool_name == "get_current_session_context":
                     ss = _get_session_state(session_id)
                     # Return non-null values
                     context_data = {k: v for k, v in ss.items() if v}
                     if not context_data:
                         context_data = {"info": "No active session context (no facility/location selected yet)."}
                     
                     raw_output = json.dumps(context_data)
                     current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                     tools_used_summary.append(f"{tool_name}: {raw_output}")
                     
                     # NEW: Store in memory
                     if memory_store:
                         try:
                             memory_store.add_tool_execution(
                                 session_id=session_id,
                                 tool_name=tool_name,
                                 tool_args={},
                                 tool_output=raw_output
                             )
                         except Exception as e:
                             print(f"DEBUG: Error storing context tool in memory: {e}")
                     
                     last_intent = "context_check"
                     last_data = context_data
                     continue

                # 1. Internal Tool: Clear Session Context
                if tool_name == "clear_session_context":
                    scope = tool_args.get("scope", "transient") if isinstance(tool_args, dict) else "transient"
                    cleared_keys = _clear_session_context(session_id, scope)
                    
                    result = {
                        "status": "success",
                        "cleared_keys": cleared_keys,
                        "remaining_context": dict(_get_session_state(session_id))
                    }
                    
                    raw_output = json.dumps(result)
                    current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                    tools_used_summary.append(f"{tool_name}({scope}): Cleared {len(cleared_keys)} keys")
                    
                    # Store in memory
                    if memory_store:
                        try:
                            memory_store.add_tool_execution(
                                session_id=session_id,
                                tool_name=tool_name,
                                tool_args={"scope": scope},
                                tool_output=raw_output
                            )
                        except Exception as e:
                            print(f"DEBUG: Error storing clear context in memory: {e}")
                    
                    last_intent = "session_clear"
                    last_data = result
                    continue

                # 2a. Internal Tool: Decide Search or Analyze (Decision Helper)
                if tool_name == "decide_search_or_analyze":
                    try:
                        user_query = tool_args.get("user_query", "").lower()
                        report_size = tool_args.get("report_size", 0)
                        
                        # Decision logic: search keywords vs direct analysis
                        search_keywords = ["pattern", "trend", "concern", "similar", "unusual", "most", "least", "compare", "correlation"]
                        use_search = any(kw in user_query for kw in search_keywords) or report_size > 200
                        
                        result = {
                            "use_search": use_search,
                            "approach": "search_embedded_report" if use_search else "direct_analysis",
                            "reason": "Exploratory/correlation query detected" if use_search else "Specific query - direct analysis sufficient"
                        }
                        
                        raw_output = json.dumps(result)
                        current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                        tools_used_summary.append(f"{tool_name}: use_search={use_search}")
                        
                        # Store in memory
                        if memory_store:
                            try:
                                memory_store.add_tool_execution(
                                    session_id=session_id,
                                    tool_name=tool_name,
                                    tool_args=tool_args,
                                    tool_output=raw_output
                                )
                            except Exception as e:
                                print(f"DEBUG: Error storing decision in memory: {e}")
                        
                        last_intent = "query_decision"
                        last_data = result
                        continue
                        
                    except Exception as e:
                        error_msg = f"Error in decide_search_or_analyze: {str(e)}"
                        print(f"DEBUG: {error_msg}")
                        raw_output = json.dumps({"error": error_msg})
                        current_context_text += f"\nTool '{tool_name}' Error: {raw_output}\n"
                    
                    continue

                # 2b. Internal Tool: Embed Report for Exploration (Dynamic RAG)
                if tool_name == "embed_report_for_exploration":
                    try:
                        # Removed agent type restriction - RAG available for all agents
                        
                        if not isinstance(tool_args, dict):
                            raise ValueError("tool_args must be a dict")
                        
                        report_obj = tool_args.get("report_data")
                        if not report_obj or not isinstance(report_obj, dict):
                            raise ValueError("report_data must be a dict object from get_reports")
                        
                        # Extract report type and data
                        report_type = report_obj.get("report_type", "unknown")
                        
                        # Handle both chunked and non-chunked reports
                        if report_obj.get("is_chunked"):
                            report_data = report_obj.get("sample_data", [])
                            print(f"DEBUG: Embedding chunked report (sample data only)")
                        else:
                            report_data = report_obj.get("data", [])
                        
                        if not report_data:
                            raise ValueError("No data found in report")
                        
                        # Embed the report
                        result = memory_store.embed_report_for_session(
                            session_id=session_id,
                            report_data=report_data,
                            report_type=report_type,
                            chunk_size=50
                        )
                        
                        raw_output = json.dumps(result)
                        current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                        tools_used_summary.append(
                            f"{tool_name}: Embedded {result.get('chunks_embedded', 0)} chunks"
                        )
                        
                        last_intent = "embed_report"
                        last_data = result
                        
                    except Exception as e:
                        error_msg = f"Error embedding report: {str(e)}"
                        print(f"DEBUG: {error_msg}")
                        raw_output = json.dumps({"error": error_msg})
                        current_context_text += f"\nTool '{tool_name}' Error: {raw_output}\n"
                    
                    continue

                # 2b. Internal Tool: Search Embedded Report (Dynamic RAG)
                if tool_name == "search_embedded_report":
                    print(f"DEBUG: 🔍 SEARCH_EMBEDDED_REPORT CALLED")
                    try:
                        # Removed agent type restriction - search available for all agents
                        
                        if not isinstance(tool_args, dict):
                            raise ValueError("tool_args must be a dict")
                        
                        query = tool_args.get("query", "").strip()
                        if not query:
                            raise ValueError("query parameter is required")
                        
                        n_results = tool_args.get("n_results", 3)
                        if not isinstance(n_results, int):
                            n_results = 3
                        
                        print(f"DEBUG: Search query: '{query}'")
                        print(f"DEBUG: Max results: {n_results}")
                        print(f"DEBUG: Session ID: {session_id}")
                        
                        # Search session embeddings
                        results = memory_store.search_embedded_report(
                            session_id=session_id,
                            query=query,
                            n_results=n_results
                        )
                        
                        print(f"DEBUG: ✅ SEARCH RETURNED {len(results.get('results', []))} results")
                        print(f"DEBUG: Search results summary: {results}")
                        
                        result = {
                            "query": query,
                            "results_found": len(results.get('results', [])),
                            "chunks": results.get('results', [])
                        }
                        
                        raw_output = json.dumps(result, default=str)
                        current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                        tools_used_summary.append(
                            f"{tool_name}('{query}'): Found {len(results)} relevant chunks"
                        )
                        
                        last_intent = "search_embeddings"
                        last_data = result
                        
                    except Exception as e:
                        error_msg = f"Error searching embeddings: {str(e)}"
                        print(f"DEBUG: {error_msg}")
                        raw_output = json.dumps({"error": error_msg})
                        current_context_text += f"\nTool '{tool_name}' Error: {raw_output}\n"
                    
                    continue

                # 2. Internal Tool: Memory
                if tool_name == "query_past_conversations":
                    try:
                        query = ""
                        if isinstance(tool_args, dict):
                            query = str(tool_args.get("query") or "").strip()
                        n_results = 5
                        scope = "all"
                        if isinstance(tool_args, dict):
                            if tool_args.get("n_results") is not None:
                                try:
                                    n_results = int(tool_args.get("n_results"))
                                except Exception:
                                    n_results = 5
                            if tool_args.get("scope") in ("all", "session"):
                                scope = tool_args.get("scope")

                        if not query:
                            raw_output = json.dumps({"memories": [], "error": "missing_query"})
                            current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                            tools_used_summary.append(f"{tool_name}: {raw_output}")
                            last_intent = "memory_query"
                            last_data = {"memories": [], "error": "missing_query"}
                            continue

                        if not memory_store:
                            raw_output = json.dumps({"memories": [], "error": "memory_disabled"})
                            current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                            tools_used_summary.append(f"{tool_name}: {raw_output}")
                            last_intent = "memory_query"
                            last_data = {"memories": [], "error": "memory_disabled"}
                            continue

                        where = None
                        if scope == "session":
                            where = {"session_id": session_id}

                        memories = memory_store.query_memory(query, n_results=n_results, where=where)
                        raw_output = json.dumps({"memories": memories, "scope": scope})

                        current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                        tools_used_summary.append(f"{tool_name}: {raw_output[:500]}...")
                        last_intent = "memory_query"
                        last_data = {"memories": memories, "scope": scope}
                        continue
                    except Exception as e:
                        current_context_text += f"\nSystem: Error executing internal tool {tool_name}: {str(e)}\n"
                        continue
                
                # 3. Custom Tools (Webhook)
                if tool_name not in tool_router:
                     # Check if it is a Custom Dynamic Tool
                     custom_tools = load_custom_tools()
                     target_tool = next((t for t in custom_tools if t['name'] == tool_name), None)
                     
                     if target_tool:
                         print(f"Executing Custom Tool {tool_name} via Webhook...")
                         try:
                             # Generic Webhook Execution
                             method = target_tool.get("method", "POST")
                             url = target_tool.get("url")
                             headers = target_tool.get("headers", {})
                             if not url: raise ValueError("No URL configured for this tool.")

                             # tool_args already processed via global sticky args
                             
                             # We assume n8n/webhook style: POST with JSON body
                             resp = await client.request(method, url, json=tool_args, headers=headers, timeout=30.0)
                             
                            
                             # Try to parse JSON response
                             json_resp = None
                             try:
                                 json_resp = resp.json()
                                 
                                 print(f"DEBUG: JSON Response: {json_resp}")
                                 # 1. Output Filtering (if outputSchema properties defined)
                                 # This is a basic filter: if 'properties' are defined in outputSchema, 
                                 # we only keep those keys from the root level of the response.
                                 output_schema = target_tool.get("outputSchema", {})
                                 if output_schema and "properties" in output_schema and isinstance(json_resp, dict):
                                     filtered_resp = {}
                                     for key in output_schema["properties"].keys():
                                         if key in json_resp:
                                             filtered_resp[key] = json_resp[key]
                                     # If we found matching keys, use the filtered version
                                     if filtered_resp:
                                         json_resp = filtered_resp

                                 raw_output = json.dumps(json_resp)
                             except Exception as e:
                                 print(f"DEBUG: Failed to parse JSON from {url}: {e}")
                                 raw_output = resp.text
                                 if not raw_output:
                                     print(f"DEBUG: ❌ Empty response from {tool_name} (Status: {resp.status_code})")
                                     raw_output = json.dumps({"error": f"Empty response from tool {tool_name} (Status: {resp.status_code})"})
                                 
                                 
                             current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                             tools_used_summary.append(f"{tool_name}: {raw_output[:500]}...")
                             
                             # NEW: Extract and persist IDs for custom tools too
                             _extract_and_persist_ids(session_id, tool_name, raw_output)
                             
                             # NEW: Auto-embed report tools (skip normal embedding)
                             if memory_store:
                                 try:
                                     print(f"DEBUG: Checking tool_type for '{tool_name}': {target_tool.get('tool_type')}")
                                     if target_tool.get("tool_type") == "report":
                                         # Report tools: auto-embed via RAG (skip normal embedding)
                                         print(f"DEBUG: ✅ REPORT TOOL DETECTED - Starting auto-embed for '{tool_name}'")
                                         try:
                                             parsed_output = json.loads(raw_output)
                                             print(f"DEBUG: Parsed report output: {len(parsed_output)} report(s)")
                                             
                                             # Automatically embed each report
                                             if isinstance(parsed_output, list):
                                                 for idx, report_obj in enumerate(parsed_output):
                                                     if isinstance(report_obj, dict) and "data" in report_obj:
                                                         if report_obj.get("is_file"):
                                                             print(f"DEBUG: 📂 Report #{idx+1} is a FILE. Skipping auto-embedding.")
                                                             continue
                                                         report_type = report_obj.get("report", "unknown")
                                                         report_data = report_obj.get("data", [])
                                                         
                                                         print(f"DEBUG: 📊 AUTO-EMBEDDING REPORT #{idx+1}: '{report_type}' with {len(report_data)} rows")
                                                         print(f"DEBUG: Session ID: {session_id}")
                                                         
                                                         embed_result = memory_store.embed_report_for_session(
                                                             session_id=session_id,
                                                             report_data=report_data,
                                                             report_type=report_type,
                                                             chunk_size=50  # Stays within token limits
                                                         )
                                                         
                                                         chunks_count = embed_result.get('chunks_embedded', 0)
                                                         print(f"DEBUG: ✅ SUCCESSFULLY EMBEDDED {chunks_count} chunks for '{report_type}'")
                                                         print(f"DEBUG: Embed result: {embed_result}")
                                                     else:
                                                         print(f"DEBUG: ⚠️ Skipping report #{idx+1} - missing 'data' field")
                                             else:
                                                 print(f"DEBUG: ⚠️ Report output is not a list: {type(parsed_output)}")
                                             
                                             print(f"DEBUG: 🎯 SKIPPED normal embedding for report tool '{tool_name}' (using RAG instead)")
                                             
                                         except Exception as e:
                                             print(f"DEBUG: ❌ ERROR auto-embedding report: {e}")
                                             import traceback
                                             traceback.print_exc()
                                             # Graceful degradation - continue without embedding
                                     else:
                                         # Normal tools: use standard embedding
                                         print(f"DEBUG: Using normal embedding for non-report tool '{tool_name}'")
                                         memory_store.add_tool_execution(
                                             session_id=session_id,
                                             tool_name=tool_name,
                                             tool_args=tool_args,
                                             tool_output=raw_output
                                         )
                                 except Exception as e:
                                     print(f"DEBUG: Error storing custom tool in memory: {e}")
                             
                             # Capture intent/data before continuing (restarting loop)
                             last_intent = "custom_tool"
                             # Return the final tool output as structured JSON directly under `data`
                             # (n8n often returns a list; keep it as a list instead of string-wrapping)
                             if json_resp is not None:
                                 last_data = json_resp
                             else:
                                 last_data = {"output": raw_output}
                             
                             # Continue loop
                             continue
                         except Exception as e:
                             current_context_text += f"\nSystem: Error executing custom tool {tool_name}: {str(e)}\n"
                             continue
                             
                     # Hallucinated tool, append error and continue
                     current_context_text += f"\nSystem: Error - Tool '{tool_name}' not found. Please try a valid tool.\n"
                     continue

                # 4. MCP Tools
                agent_name = tool_router[tool_name]
                session = agent_sessions[agent_name]
                
                print(f"Executing {tool_name} on {agent_name}...")
                try:
                    # tool_args already processed
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

                        if tool_name == "collect_data":
                            last_intent = "collect_data"
                            last_data = parsed

                    except:
                        pass

                    # Append Result to Context
                    # Increase truncation limit to 50k to allow full email contents to be passed to next steps
                    display_output = raw_output[:50000] + "...(truncated)" if len(raw_output) > 50000 else raw_output
                    print(f"DEBUG: Tool Output Length: {len(raw_output)}", flush=True)
                    print(f"DEBUG: Tool Output Content: {raw_output}", flush=True)
                    current_context_text += f"\nTool '{tool_name}' Output: {display_output}\n"
                    
                    # NEW: Extract and persist critical IDs to session state
                    _extract_and_persist_ids(session_id, tool_name, raw_output)
                    
                    # NEW: Store tool execution in memory for retrieval
                    if memory_store:
                        try:
                            memory_store.add_tool_execution(
                                session_id=session_id,
                                tool_name=tool_name,
                                tool_args=tool_args,
                                tool_output=raw_output
                            )
                        except Exception as e:
                            print(f"DEBUG: Error storing tool execution in memory: {e}")
                    
                    tools_used_summary.append(f"{tool_name}: {display_output[:500]}...")

                    
                except Exception as e:
                    current_context_text += f"\nSystem: Error executing tool {tool_name}: {str(e)}\n"
            
            else:
                # No tool call, this is the final answer
                final_response = llm_output
                break
        
        if not final_response:
             final_response = "I completed the requested actions." # Fallback if loop finishes with tool usage


        
    # 4. Save to Memory (Background Task ideal, but inline for POC)
    if memory_store and final_response:
        memory_store.add_memory("user", user_message, metadata={"session_id": session_id})
        memory_store.add_memory("assistant", final_response, metadata={"session_id": session_id})
        
    # Save to Short-Term History (session-scoped)
    _get_conversation_history(session_id).append({
        "user": user_message,
        "assistant": final_response,
        "tools": tools_used_summary
    })
    print(f"DEBUG: Conversation History Updated. session_id={session_id} length={len(_get_conversation_history(session_id))}")
        
    return ChatResponse(
        response=final_response,
        intent=last_intent,
        data=last_data,
        tool_name=tool_name
    )

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Real-time streaming endpoint with SSE"""
    print(f"[SSE] Endpoint called with message: {request.message[:50]}...")
    
    async def event_generator():
        try:
            if not agent_sessions:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No agents connected'})}\n\n"
                return

            session_id = _get_session_id(request)
            user_message = request.message

            # Merge client-provided ephemeral state into server session state (best-effort)
            ss = _get_session_state(session_id)
            if request.client_state and isinstance(request.client_state, dict):
                active_facility = request.client_state.get("active_facility_id")
                if active_facility:
                    ss["facility_id"] = str(active_facility)
            
            # Start streaming - send status
            status_event = json.dumps({'type': 'status', 'message': 'Processing your request...'})
            print(f"[SSE] Sending status event: {status_event}")
            yield f"data: {status_event}\n\n"
            await asyncio.sleep(0)  # Allow event to be sent
            
            # 1. Aggregate Tools & Build Schema Map
            all_tools = []
            tool_schema_map = {}  # name -> inputSchema
            
            # -- Load Active Agent Logic --
            try:
                # Helper to get active agent data (mock implementation if missing)
                # In chat_stream we don't have get_active_agent_data imported or defined in scope?
                # Actually it seems it was available.
                active_agent = get_active_agent_data()
            except:
                # Fallback if function not available
                active_agent = {"tools": ["all"], "type": "general"}

            allowed_tools = active_agent.get("tools", ["all"])
            
            # CRITICAL: Auto-inject RAG tools for ANY analysis agent
            if active_agent.get("type") == "analysis":
                if "decide_search_or_analyze" not in allowed_tools:
                    allowed_tools.append("decide_search_or_analyze")
                if "search_embedded_report" not in allowed_tools:
                    allowed_tools.append("search_embedded_report")
            
            agent_system_template = active_agent.get("system_prompt", NATIVE_TOOL_SYSTEM_PROMPT)
            
            # DYNAMIC RAG INJECTION
            # If we have active embeddings, force the LLM to know about them
            try:
                ss = _get_session_state(session_id)
                last_report = ss.get("last_report_context")
                if last_report and (time.time() - last_report.get("timestamp", 0) < 600): # 10 mins validity
                    rag_context_msg = f"""
### ACTIVE RAG CONTEXT (AUTOMATICALLY INJECTED)
You have {last_report.get('row_count', 'some')} rows of '{last_report.get('type', 'report')}' data embedded in memory (generated {int(time.time() - last_report.get('timestamp', 0))}s ago).
For questions about this data:
1. **CHECK CONTEXT FIRST:** If the data is visible above, analyze it directly.
2. **USE SEARCH:** For "patterns", "trends", or "specific units" not visible, start by calling `search_embedded_report`.
3. **DO NOT RE-RUN REPORT:** The data is already here. Only call report tools if the user implicitly asks for NEW data (e.g. "refresh", "different property").
"""
                    # Inject into system prompt
                    agent_system_template += rag_context_msg
                    print(f"DEBUG: 💉 Injected RAG context into system prompt")
            except Exception as e:
                print(f"DEBUG: Error injecting RAG prompt: {e}")
            
            # Standard MCP Tools
            for session in agent_sessions.values():
                result = await session.list_tools()
                if "all" in allowed_tools:
                    all_tools.extend(result.tools)
                else:
                    for t in result.tools:
                        if t.name in allowed_tools:
                            all_tools.extend([t])

            # Populate schema map for MCP tools
            for t in all_tools:
                tool_schema_map[t.name] = t.inputSchema

            # Dynamic Custom Tools (n8n/Webhook)
            custom_tools = load_custom_tools()
            class VirtualTool:
                def __init__(self, name, description, inputSchema):
                    self.name = name
                    self.description = description
                    self.inputSchema = inputSchema

            # Add virtual/internal tools
            mem_tool = VirtualTool(
                "query_past_conversations",
                "Search long-term conversation memory. Use this only when you need context from older sessions.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "n_results": {"type": "integer", "default": 5},
                        "scope": {"type": "string", "enum": ["all", "session"], "default": "all"},
                    },
                    "required": ["query"],
                },
            )
            all_tools.append(mem_tool)
            tool_schema_map[mem_tool.name] = mem_tool.inputSchema

            context_tool = VirtualTool(
                "get_current_session_context",
                "Get valid IDs (facility_id, etc.) and location from the current active session state.",
                {"type": "object", "properties": {}, "required": []}
            )
            all_tools.append(context_tool)
            tool_schema_map[context_tool.name] = context_tool.inputSchema

            clear_context_tool = VirtualTool(
                "clear_session_context",
                "Clear session state to start a fresh flow.",
                {
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "enum": ["transient", "all", "ids_only"],
                            "default": "transient",
                        }
                    },
                    "required": []
                }
            )
            all_tools.append(clear_context_tool)
            tool_schema_map[clear_context_tool.name] = clear_context_tool.inputSchema
            
            for ct in custom_tools:
                if "all" in allowed_tools or ct['name'] in allowed_tools:
                    vt = VirtualTool(ct['name'], ct['description'], ct['inputSchema'])
                    all_tools.append(vt)
                    tool_schema_map[vt.name] = vt.inputSchema

            # 2. System Prompt
            ollama_tools = [{'type': 'function', 'function': {'name': t.name, 'description': t.description, 'parameters': t.inputSchema}} for t in all_tools]
            tools_json = str([{'tool': t.name, 'description': t.description, 'schema': t.inputSchema} for t in all_tools])
            
            TOOL_USAGE_INSTRUCTION = """
            
            ### CURRENT DATE & TIME CONTEXT
            **Current Date:** {current_date}
            **Current Time:** {current_time}
            **Timezone:** {timezone}
            
            **IMPORTANT:** When tools return dates or timestamps, DO NOT add your own temporal context. Simply present the date/time returned by the tool.
            
            ### RESPONSE FORMAT INSTRUCTIONS
            If you need to use a specific tool from the list above, you MUST respond with **ONLY** a valid JSON object in the following format:
            { "tool": "tool_name", "arguments": { "key": "value" } }
            
            Do NOT output any other text or markdown when calling a tool.
            If you do not need to use a tool, reply in plain text.
            """
            
            # Get current date/time for context injection
            import datetime, zoneinfo
            now = datetime.datetime.now(zoneinfo.ZoneInfo("UTC"))
            current_date = now.strftime("%B %d, %Y")
            current_time = now.strftime("%I:%M %p")
            timezone = "UTC"
            
            # Inject tools, date/time, and instructions into the template
            system_prompt_text = agent_system_template.replace("{tools_json}", tools_json + TOOL_USAGE_INSTRUCTION)
            system_prompt_text = system_prompt_text.replace("{current_date}", current_date)
            system_prompt_text = system_prompt_text.replace("{current_time}", current_time)
            system_prompt_text = system_prompt_text.replace("{timezone}", timezone)

            current_settings = load_settings()
            current_model = current_settings.get("model", "mistral")
            mode = current_settings.get("mode", "local")

            # Helper functions for cloud API calls (same as original)
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
                    data = resp.json()
                    
                    if not data.get("candidates"):
                        return "Error: No response candidates from Gemini."
                    
                    candidate = data["candidates"][0]
                    if candidate.get("finishReason") == "SAFETY":
                        return "Error: Response blocked by Gemini safety filters."
                    
                    if not candidate.get("content") or not candidate["content"].get("parts"):
                        return f"Error: Malformed Gemini response. Finish Reason: {candidate.get('finishReason')}"

                    return candidate["content"]["parts"][0]["text"]

            async def call_bedrock(model_id, messages, system, region, settings):
                real_model_id = model_id.replace("bedrock.", "")
                invocation_model_id = real_model_id
                inference_profile = (settings.get("bedrock_inference_profile") or "").strip()
                if inference_profile:
                    if inference_profile.startswith("bedrock."):
                        inference_profile = inference_profile.replace("bedrock.", "", 1)
                    invocation_model_id = inference_profile
                
                bedrock = _make_aws_client("bedrock-runtime", region, settings)

                normalized_messages = []
                for m in (messages or []):
                    role = m.get("role")
                    if role not in ("user", "assistant"):
                        continue
                    content = m.get("content")
                    if isinstance(content, str):
                        normalized_messages.append({"role": role, "content": [{"text": content}]})
                    elif isinstance(content, list):
                        blocks = []
                        for b in content:
                            if isinstance(b, dict) and "text" in b:
                                blocks.append({"text": str(b.get("text"))})
                            elif isinstance(b, dict) and b.get("type") == "text" and "text" in b:
                                blocks.append({"text": str(b.get("text"))})
                            else:
                                blocks.append({"text": str(b)})
                        normalized_messages.append({"role": role, "content": blocks})
                    else:
                        normalized_messages.append({"role": role, "content": [{"text": str(content)}]})

                system_blocks = []
                if system and str(system).strip():
                    system_blocks = [{"text": str(system)}]

                async def _converse_call():
                    def _run():
                        return bedrock.converse(
                            modelId=invocation_model_id,
                            messages=normalized_messages,
                            system=system_blocks,
                            inferenceConfig={"maxTokens": 4096},
                        )
                    return await asyncio.to_thread(_run)

                async def _invoke_model_call():
                    anthropic_messages = []
                    for m in normalized_messages:
                        anthropic_messages.append(
                            {
                                "role": m["role"],
                                "content": [{"type": "text", "text": b.get("text", "")} for b in (m.get("content") or [])],
                            }
                        )

                    payload = {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 4096,
                        "system": str(system or ""),
                        "messages": anthropic_messages,
                    }

                    def _run():
                        return bedrock.invoke_model(
                            body=json.dumps(payload).encode("utf-8"),
                            modelId=invocation_model_id,
                            accept="application/json",
                            contentType="application/json",
                        )
                    return await asyncio.to_thread(_run)

                try:
                    if hasattr(bedrock, "converse"):
                        resp = await _converse_call()
                        msg = (((resp or {}).get("output") or {}).get("message") or {})
                        content = msg.get("content") or []
                        if content and isinstance(content, list) and isinstance(content[0], dict):
                            return content[0].get("text", "")
                        return ""
                except Exception as e:
                    message = str(e)
                    if "on-demand throughput isn't supported" in message:
                        raise RuntimeError(
                            "Bedrock model requires an inference profile (no on-demand throughput). "
                            "Set settings.bedrock_inference_profile to an inference profile ID/ARN."
                        )

                try:
                    resp = await _invoke_model_call()
                    response_body = json.loads(resp.get("body").read()) if resp and resp.get("body") else {}
                    content = response_body.get("content") or []
                    if content and isinstance(content, list) and isinstance(content[0], dict):
                        return content[0].get("text", "")
                    return ""
                except Exception as e:
                    message = str(e)
                    if "on-demand throughput isn't supported" in message:
                        raise RuntimeError(
                            "Bedrock model requires an inference profile (no on-demand throughput). "
                            "Set settings.bedrock_inference_profile to an inference profile ID/ARN."
                        )
                    raise

            def _messages_to_transcript(messages: list[dict] | None) -> str:
                if not messages:
                    return ""
                lines: list[str] = []
                for m in messages:
                    if not isinstance(m, dict):
                        continue
                    role = (m.get("role") or "").strip().lower()
                    content = m.get("content")
                    if isinstance(content, list):
                        parts: list[str] = []
                        for p in content:
                            if isinstance(p, dict) and isinstance(p.get("text"), str):
                                parts.append(p["text"])
                        text = "\n".join(parts).strip()
                    else:
                        text = (content or "").strip() if isinstance(content, str) else ""

                    if not text:
                        continue

                    if role == "user":
                        label = "User"
                    elif role == "assistant":
                        label = "Assistant"
                    elif role:
                        label = role.title()
                    else:
                        label = "Message"
                    lines.append(f"{label}: {text}")
                return "\n".join(lines)

            async def generate_response(
                prompt_msg,
                sys_prompt,
                tools=None,
                history_messages=None,
                memory_context_text: str = "",
            ):
                augmented_system = (sys_prompt or "").strip()
                if memory_context_text and memory_context_text.strip():
                    augmented_system = f"{augmented_system}\n\n{memory_context_text.strip()}".strip()

                if mode in ["cloud", "bedrock"]:
                    try:
                        messages = []
                        if history_messages:
                            messages.extend(history_messages)
                        messages.append({"role": "user", "content": prompt_msg})

                        if current_model.startswith("gpt"):
                            return await call_openai(
                                current_model,
                                [{"role": "system", "content": augmented_system}] + messages,
                                current_settings.get("openai_key"),
                            )
                        elif current_model.startswith("claude"):
                            return await call_anthropic(
                                current_model,
                                messages,
                                augmented_system,
                                current_settings.get("anthropic_key"),
                            )
                        elif current_model.startswith("gemini"):
                            transcript = _messages_to_transcript(messages)
                            return await call_gemini(
                                current_model,
                                transcript or str(prompt_msg),
                                augmented_system,
                                current_settings.get("gemini_key"),
                            )
                        elif current_model.startswith("bedrock"):
                            return await call_bedrock(
                                current_model,
                                messages,
                                augmented_system,
                                current_settings.get("aws_region"),
                                current_settings,
                            )
                        else:
                            return "Error: Unknown cloud model selected."
                    except Exception as e:
                        return f"Cloud API Error: {str(e)}"
                
                # Local Ollama
                async with httpx.AsyncClient() as client:
                    try:
                        if tools:
                            messages = [{"role": "system", "content": augmented_system}]
                            if history_messages:
                                messages.extend(history_messages)
                            messages.append({"role": "user", "content": prompt_msg})

                            response = await client.post(
                                f"{OLLAMA_BASE_URL}/api/chat",
                                json={
                                    "model": current_model,
                                    "messages": messages,
                                    "tools": tools,
                                    "stream": False
                                },
                                timeout=None
                            )
                            response.raise_for_status()
                            data = response.json()
                            msg = data.get("message", {})
                            
                            if "tool_calls" in msg and msg["tool_calls"]:
                                tc = msg["tool_calls"][0]
                                return json.dumps({
                                    "tool": tc["function"]["name"], 
                                    "arguments": tc["function"]["arguments"]
                                })
                            
                            return msg.get("content", "")

                        prompt_for_generate = prompt_msg
                        if history_messages:
                            prior = _messages_to_transcript(history_messages)
                            if prior:
                                prompt_for_generate = f"Conversation so far:\n{prior}\n\nUser: {prompt_msg}".strip()

                        response = await client.post(
                            f"{OLLAMA_BASE_URL}/api/generate",
                            json={
                                "model": current_model,
                                "prompt": prompt_for_generate,
                                "system": augmented_system,
                                "stream": False
                            },
                            timeout=None
                        )
                        response.raise_for_status()
                        return response.json().get("response", "")
                    except Exception as e:
                        return f"Local Agent Error: {e}"

            # --- ReAct Loop with Streaming ---
            memory_context = ""
            recent_history_messages = get_recent_history_messages(session_id)
            current_context_text = f"User Request: {user_message}\n"

            # Inject session context
            active_ss = _get_session_state(session_id)
            if active_ss:
                valid_context = {k: v for k, v in active_ss.items() if v}
                if valid_context:
                    context_str = json.dumps(valid_context, indent=2)
                    system_prompt_text += f"\n\n### CURRENT SESSION CONTEXT ###\nThe following variables are active in the current session:\n{context_str}\n"
            
            # Inject recent tool outputs
            if memory_store:
                try:
                    recent_tools = memory_store.get_session_tool_outputs(
                        session_id=session_id,
                        n_results=5
                    )
                    
                    if recent_tools and recent_tools.get('documents'):
                        tools_summary = "\n".join([f"- {doc}" for doc in recent_tools['documents']])
                        system_prompt_text += f"""

### RECENT TOOL EXECUTIONS ###
The following tools were executed recently in this session:
{tools_summary}

### SESSION LIFECYCLE MANAGEMENT ###
When you detect the user wants to start a NEW operation, call clear_session_context() BEFORE calling other tools.
"""
                except Exception as e:
                    print(f"DEBUG: Error injecting tool history: {e}")
            
            final_response = ""
            last_intent = "chat"
            last_data = None
            tool_name = None
            tools_used_summary = []
            tool_repetition_counts = {}
            
            # === Main ReAct Loop ===
            current_turn = 0
            
            async with httpx.AsyncClient() as client:
                while current_turn < MAX_TURNS:
                    current_turn += 1
                    
                    # Display turn number in terminal
                    print(f"\n{'#'*60}")
                    print(f"### TURN {current_turn}/{MAX_TURNS} ###")
                    print(f"{'#'*60}\n")
                    
                    # Stream thinking event
                    yield f"data: {json.dumps({'type': 'thinking', 'message': 'Analyzing your request...'})}\n\n"
                    await asyncio.sleep(0)
                    
                    if current_turn == 1:
                        active_sys_prompt = system_prompt_text
                        active_prompt = user_message 
                        active_history = recent_history_messages
                    else:
                        active_sys_prompt = system_prompt_text
                        active_prompt = current_context_text
                        active_history = []
                    
                    llm_output = await generate_response(
                        active_prompt, 
                        active_sys_prompt, 
                        tools=ollama_tools, 
                        history_messages=active_history,
                        memory_context_text=memory_context,
                    )
                    
                    # Parse Tool Call
                    import re
                    tool_call = None
                    json_error = None
                    
                    try:
                        cleaned_output = llm_output.replace("```json", "").replace("```", "").strip()
                        try:
                            tool_call = json.loads(cleaned_output)
                        except:
                            json_match = re.search(r'\{.*\}', cleaned_output, re.DOTALL)
                            if json_match:
                                tool_call = json.loads(json_match.group(0))
                    except Exception as e:
                        json_error = str(e)

                    # Debug: Log raw LLM output
                    print(f"[DEBUG] LLM RAW OUTPUT: {llm_output[:200]}...")
                    print(f"[DEBUG] Parsed tool_call: {tool_call}")
                    
                    if json_error:
                        print(f"[DEBUG] JSON Parsing Error: {json_error}")
                        current_context_text += f"\nSystem: JSON Parsing Error: {json_error}. Please Try Again with valid JSON.\n"
                        continue

                    # Support both formats: {"tool": "...", "arguments": {...}} and {"name": "...", "arguments": {...}}
                    if tool_call and isinstance(tool_call, dict) and ("tool" in tool_call or "name" in tool_call):
                        tool_name = tool_call.get("tool") or tool_call.get("name")
                        tool_args = tool_call.get("arguments", {})
                        
                        # Apply sticky args
                        tool_schema = tool_schema_map.get(tool_name)
                        tool_args = _apply_sticky_args(session_id, tool_name, tool_args, tool_schema)
                        
                        # Debug logging
                        print(f"\n{'='*60}")
                        print(f"TOOL CALL: {tool_name}")
                        print(f"ARGUMENTS: {json.dumps(tool_args, indent=2)}")
                        print(f"{'='*60}\n")
                        
                        # Stream tool execution event
                        yield f"data: {json.dumps({'type': 'tool_execution', 'tool_name': tool_name, 'args': tool_args})}\n\n"
                        await asyncio.sleep(0)

                        # Loop guard
                        current_tool_signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                        tool_repetition_counts[current_tool_signature] = tool_repetition_counts.get(current_tool_signature, 0) + 1
                        
                        if tool_repetition_counts[current_tool_signature] > 1:
                            current_context_text += f"\nSystem: You just called '{tool_name}' with these exact arguments. STOP. Summarize the results.\n"
                            continue

                        # Execute tool (internal tools)
                        if tool_name == "get_current_session_context":
                            ss = _get_session_state(session_id)
                            result = {
                                "session_id": session_id,
                                "active_facility_id": ss.get("facility_id"),
                                "personal_details": ss.get("personal_details", {})
                            }
                            raw_output = json.dumps(result)
                            
                            # Debug logging for internal tool
                            print(f"\n{'='*60}")
                            print(f"INTERNAL TOOL RESULT: {tool_name}")
                            print(f"OUTPUT: {raw_output}")
                            print(f"{'='*60}\n")
                            
                            current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                            tools_used_summary.append(f"{tool_name}: {raw_output}")
                            
                            if memory_store:
                                try:
                                    memory_store.add_tool_execution(
                                        session_id=session_id,
                                        tool_name=tool_name,
                                        tool_args={},
                                        tool_output=raw_output
                                    )
                                except Exception as e:
                                    print(f"DEBUG: Error storing context tool: {e}")
                            
                            # Stream result
                            yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': 'Session context retrieved'})}\n\n"
                            await asyncio.sleep(0)
                            
                            last_intent = "context_check"
                            last_data = context_data
                            continue

                        if tool_name == "clear_session_context":
                            scope = tool_args.get("scope", "transient") if isinstance(tool_args, dict) else "transient"
                            cleared_keys = _clear_session_context(session_id, scope)
                            
                            result = {
                                "status": "success",
                                "cleared_keys": cleared_keys,
                                "remaining_context": dict(_get_session_state(session_id))
                            }
                            
                            raw_output = json.dumps(result)
                            current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                            tools_used_summary.append(f"{tool_name}({scope}): Cleared {len(cleared_keys)} keys")
                            
                            if memory_store:
                                try:
                                    memory_store.add_tool_execution(
                                        session_id=session_id,
                                        tool_name=tool_name,
                                        tool_args={"scope": scope},
                                        tool_output=raw_output
                                    )
                                except Exception as e:
                                    print(f"DEBUG: Error storing clear context: {e}")
                            
                            # Stream result
                            yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': f'Cleared {len(cleared_keys)} items'})}\n\n"
                            await asyncio.sleep(0)
                            
                            last_intent = "session_clear"
                            last_data = result
                            continue

                        # 2a. Internal Tool: Embed Report for Exploration (Dynamic RAG)
                        if tool_name == "embed_report_for_exploration":
                            try:
                                # CRITICAL: Only allow RAG for analysis agents
                                if active_agent.get("type") != "analysis":
                                    raise ValueError("Dynamic RAG is only available for analysis-type agents")
                                
                                if not isinstance(tool_args, dict):
                                    raise ValueError("tool_args must be a dict")
                                
                                report_obj = tool_args.get("report_data")
                                if not report_obj or not isinstance(report_obj, dict):
                                    raise ValueError("report_data must be a dict object from get_reports")
                                
                                report_type = report_obj.get("report_type", "unknown")
                                
                                if report_obj.get("is_chunked"):
                                    report_data = report_obj.get("sample_data", [])
                                else:
                                    report_data = report_obj.get("data", [])
                                
                                if not report_data:
                                    raise ValueError("No data found in report")
                                
                                result = memory_store.embed_report_for_session(
                                    session_id=session_id,
                                    report_data=report_data,
                                    report_type=report_type,
                                    chunk_size=50
                                )
                                
                                raw_output = json.dumps(result)
                                current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                tools_used_summary.append(
                                    f"{tool_name}: Embedded {result.get('chunks_embedded', 0)} chunks"
                                )
                                
                                # Stream result
                                chunks_embedded = result.get("chunks_embedded", 0)
                                preview_msg = f"Embedded {chunks_embedded} chunks"
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': preview_msg})}\n\n"
                                await asyncio.sleep(0)
                                
                                last_intent = "embed_report"
                                last_data = result
                                
                            except Exception as e:
                                error_msg = f"Error embedding report: {str(e)}"
                                raw_output = json.dumps({"error": error_msg})
                                current_context_text += f"\nTool '{tool_name}' Error: {raw_output}\n"
                            
                            continue

                        # 2b. Internal Tool: Search Embedded Report (Dynamic RAG)
                        if tool_name == "search_embedded_report":
                            try:
                                # CRITICAL: Only allow RAG for analysis agents
                                if active_agent.get("type") != "analysis":
                                    raise ValueError("Dynamic RAG is only available for analysis-type agents")
                                
                                if not isinstance(tool_args, dict):
                                    raise ValueError("tool_args must be a dict")
                                
                                query = tool_args.get("query", "").strip()
                                if not query:
                                    raise ValueError("query parameter is required")
                                
                                n_results = tool_args.get("n_results", 3)
                                if not isinstance(n_results, int):
                                    n_results = 3
                                
                                results = memory_store.search_session_embeddings(
                                    session_id=session_id,
                                    query=query,
                                    n_results=n_results
                                )
                                
                                result = {
                                    "query": query,
                                    "results_found": len(results),
                                    "chunks": results
                                }
                                
                                raw_output = json.dumps(result, default=str)
                                current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                tools_used_summary.append(
                                    f"{tool_name}('{query}'): Found {len(results)} relevant chunks"
                                )
                                
                                # Stream result
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': f'Found {len(results)} relevant chunks'})}\n\n"
                                await asyncio.sleep(0)
                                
                                last_intent = "search_embeddings"
                                last_data = result
                                
                            except Exception as e:
                                error_msg = f"Error searching embeddings: {str(e)}"
                                raw_output = json.dumps({"error": error_msg})
                                current_context_text += f"\nTool '{tool_name}' Error: {raw_output}\n"
                            
                            continue

                        if tool_name == "query_past_conversations":
                            try:
                                query = ""
                                if isinstance(tool_args, dict):
                                    query = str(tool_args.get("query") or "").strip()
                                n_results = 5
                                scope = "all"
                                if isinstance(tool_args, dict):
                                    if tool_args.get("n_results") is not None:
                                        try:
                                            n_results = int(tool_args.get("n_results"))
                                        except Exception:
                                            n_results = 5
                                    if tool_args.get("scope") in ("all", "session"):
                                        scope = tool_args.get("scope")

                                if not query:
                                    raw_output = json.dumps({"memories": [], "error": "missing_query"})
                                    current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                    tools_used_summary.append(f"{tool_name}: {raw_output}")
                                    last_intent = "memory_query"
                                    last_data = {"memories": [], "error": "missing_query"}
                                    continue

                                if not memory_store:
                                    raw_output = json.dumps({"memories": [], "error": "memory_disabled"})
                                    current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                    tools_used_summary.append(f"{tool_name}: {raw_output}")
                                    last_intent = "memory_query"
                                    last_data = {"memories": [], "error": "memory_disabled"}
                                    continue

                                where = None
                                if scope == "session":
                                    where = {"session_id": session_id}

                                memories = memory_store.query_memory(query, n_results=n_results, where=where)
                                raw_output = json.dumps({"memories": memories, "scope": scope})

                                current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                tools_used_summary.append(f"{tool_name}: {raw_output[:500]}...")
                                
                                # Stream result
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': f'Found {len(memories)} memories'})}\n\n"
                                await asyncio.sleep(0)
                                
                                last_intent = "memory_query"
                                last_data = {"memories": memories, "scope": scope}
                                continue
                            except Exception as e:
                                current_context_text += f"\nSystem: Error executing internal tool {tool_name}: {str(e)}\n"
                                continue
                        
                        # 2a. Internal Tool: Decide Search or Analyze (Decision Helper)
                        if tool_name == "decide_search_or_analyze":
                            try:
                                user_query = tool_args.get("user_query", "").lower()
                                report_size = tool_args.get("report_size", 0)
                                if not isinstance(report_size, int):
                                    report_size = 0
                                
                                # Heuristic keywords
                                search_keywords = ["pattern", "trend", "concern", "similar", "unusual", "most", "least", "compare", "correlation"]
                                
                                # Logic: Use search if query is exploratory OR report is large
                                use_search = any(kw in user_query for kw in search_keywords) or report_size > 200
                                
                                result = {
                                    "use_search": use_search,
                                    "approach": "search_embedded_report" if use_search else "direct_analysis",
                                    "reason": "Exploratory/correlation query detected" if use_search else "Specific query - direct analysis sufficient"
                                }
                                
                                raw_output = json.dumps(result, default=str)
                                current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                tools_used_summary.append(
                                    f"{tool_name}: Recommended {result['approach']}"
                                )
                                
                                # Persist decision
                                last_intent = "decide_rag"
                                last_data = result
                                
                                # Stream result - IMPORTANT for UI
                                # Stream result - IMPORTANT for UI
                                decision_preview = f"Decision: {result.get('approach')}"
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': decision_preview})}\n\n"
                                await asyncio.sleep(0)

                            except Exception as e:
                                error_msg = f"Error in decision logic: {str(e)}"
                                raw_output = json.dumps({"error": error_msg})
                                current_context_text += f"\nTool '{tool_name}' Error: {raw_output}\n"
                            
                            continue

                        # 2b. Internal Tool: Search Embedded Report (Dynamic RAG)
                        if tool_name == "search_embedded_report":
                            print(f"DEBUG: 🔍 SEARCH_EMBEDDED_REPORT CALLED (STREAM)")
                            try:
                                # Removed agent type restriction
                                
                                if not isinstance(tool_args, dict):
                                    raise ValueError("tool_args must be a dict")
                                
                                query = tool_args.get("query", "").strip()
                                if not query:
                                    raise ValueError("query parameter is required")
                                
                                n_results = tool_args.get("n_results", 3)
                                
                                print(f"DEBUG: Search query: '{query}'")
                                print(f"DEBUG: Max results: {n_results}")
                                print(f"DEBUG: Session ID: {session_id}")
                                
                                # Search embedded report data
                                results = memory_store.search_embedded_report(
                                    session_id=session_id,
                                    query=query,
                                    n_results=n_results
                                )
                                
                                print(f"DEBUG: ✅ SEARCH RETURNED {len(results.get('results', []))} results")
                                
                                result = {
                                    "query": query,
                                    "results_found": len(results.get('results', [])),
                                    "chunks": results.get('results', [])
                                }
                                
                                raw_output = json.dumps(result, default=str)
                                current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                tools_used_summary.append(
                                    f"{tool_name}('{query}'): Found {len(results.get('results', []))} relevant chunks"
                                )
                                
                                last_intent = "search_embeddings"
                                last_data = result
                                
                                # Stream result - IMPORTANT for UI
                                # Stream result - IMPORTANT for UI
                                results_count = len(results.get("results", []))
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': f'Found {results_count} relevant chunks'})}\n\n"
                                await asyncio.sleep(0)

                            except Exception as e:
                                error_msg = f"Error searching embeddings: {str(e)}"
                                print(f"DEBUG: {error_msg}")
                                raw_output = json.dumps({"error": error_msg})
                                current_context_text += f"\nTool '{tool_name}' Error: {raw_output}\n"
                            
                            continue

                        # Custom Tools (Webhook)
                        if tool_name not in tool_router:
                            custom_tools = load_custom_tools()
                            target_tool = next((t for t in custom_tools if t['name'] == tool_name), None)
                            
                            # REPORT CACHING/THROTTLING (GENERIC)
                            # Prevent redundant report generation if data is already in context
                            if target_tool and target_tool.get("tool_type") == "report":
                                try:
                                    ss = _get_session_state(session_id)
                                    last_report = ss.get("last_report_context")
                                    
                                    # Check if run recently (within 5 minutes)
                                    if last_report and (time.time() - last_report.get("timestamp", 0) < 300):
                                        # Check if it's the SAME report type
                                        # (Simple heuristic to avoid blocking different reports)
                                        # If needed, we can check tool args too.
                                        
                                        print(f"DEBUG: 🛑 BLOCKING REDUNDANT REPORT CALL. Last run: {time.time() - last_report.get('timestamp', 0):.1f}s ago")
                                        
                                        cached_msg = {
                                            "status": "skipped",
                                            "message": f"REPORT ALREADY GENERATED ({int(time.time() - last_report.get('timestamp', 0))}s ago). {last_report.get('row_count', 'Unknown')} rows of data are already in your context. DO NOT RE-RUN. Analyze the existing data directly or use 'search_embedded_report' for patterns."
                                        }
                                        
                                        raw_output = json.dumps(cached_msg)
                                        current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                        
                                        yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': 'Skipped (Data already in context)'})}\n\n"
                                        await asyncio.sleep(0)
                                        continue
                                except Exception as e:
                                    print(f"DEBUG: Error in report throttling: {e}")
                            
                            if target_tool:
                                try:
                                    method = target_tool.get("method", "POST")
                                    url = target_tool.get("url")
                                    headers = target_tool.get("headers", {})
                                    if not url:
                                        raise ValueError("No URL configured for this tool.")

                                    resp = await client.request(method, url, json=tool_args, headers=headers, timeout=30.0)
                                    
                                    json_resp = None
                                    try:
                                        json_resp = resp.json()
                                        output_schema = target_tool.get("outputSchema", {})
                                        if output_schema and "properties" in output_schema and isinstance(json_resp, dict):
                                            filtered_resp = {}
                                            for key in output_schema["properties"].keys():
                                                if key in json_resp:
                                                    filtered_resp[key] = json_resp[key]
                                            if filtered_resp:
                                                json_resp = filtered_resp
                                        raw_output = json.dumps(json_resp)
                                    except Exception as e:
                                        print(f"DEBUG: Failed to parse JSON from {url}: {e}")
                                        raw_output = resp.text
                                        if not raw_output:
                                            print(f"DEBUG: ❌ Empty response from {tool_name} (Status: {resp.status_code})")
                                            raw_output = json.dumps({"error": f"Empty response from tool {tool_name} (Status: {resp.status_code})"})
                                    
                                    # Debug logging for custom tool
                                    print(f"\n{'='*60}")
                                    print(f"CUSTOM TOOL RESULT: {tool_name}")
                                    print(f"OUTPUT: {raw_output[:500]}{'...' if len(raw_output) > 500 else ''}")
                                    print(f"{'='*60}\n")
                                    
                                    current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                    tools_used_summary.append(f"{tool_name}: {raw_output[:500]}...")
                                    
                                    _extract_and_persist_ids(session_id, tool_name, raw_output)
                                    
                                    
                                    if memory_store:
                                        try:
                                            # Check for report tool (RAG auto-embed)
                                            print(f"DEBUG: Checking tool_type for '{tool_name}': {target_tool.get('tool_type')}")
                                            
                                            if target_tool.get("tool_type") == "report":
                                                # Report tools: auto-embed via RAG (skip normal embedding)
                                                print(f"DEBUG: ✅ REPORT TOOL DETECTED (STREAM) - Starting auto-embed for '{tool_name}'")
                                                try:
                                                    parsed_output = json.loads(raw_output)
                                                    print(f"DEBUG: Parsed report output: {len(parsed_output)} report(s)")
                                                    
                                                    # Automatically embed each report
                                                    if isinstance(parsed_output, list):
                                                        for idx, report_obj in enumerate(parsed_output):
                                                            if isinstance(report_obj, dict) and "data" in report_obj:
                                                                if report_obj.get("is_file"):
                                                                    print(f"DEBUG: 📂 Report #{idx+1} is a FILE. Skipping auto-embedding.")
                                                                    continue
                                                                report_type = report_obj.get("report", "unknown")
                                                                report_data = report_obj.get("data", [])
                                                                
                                                                print(f"DEBUG: 📊 AUTO-EMBEDDING REPORT #{idx+1}: '{report_type}' with {len(report_data)} rows")
                                                                print(f"DEBUG: Session ID: {session_id}")
                                                                
                                                                embed_result = memory_store.embed_report_for_session(
                                                                    session_id=session_id,
                                                                    report_data=report_data,
                                                                    report_type=report_type,
                                                                    chunk_size=50  # Stays within token limits
                                                                )
                                                                
                                                                chunks_count = embed_result.get('chunks_embedded', 0)
                                                                print(f"DEBUG: ✅ SUCCESSFULLY EMBEDDED {chunks_count} chunks for '{report_type}'")
                                                                
                                                                # Update Session State with Report Context
                                                                try:
                                                                    ss = _get_session_state(session_id)
                                                                    ss["last_report_context"] = {
                                                                        "timestamp": time.time(),
                                                                        "type": report_type,
                                                                        "row_count": len(report_data)
                                                                    }
                                                                    print(f"DEBUG: 💾 Saved report context to session state")
                                                                except Exception as e:
                                                                    print(f"DEBUG: Error saving report context: {e}")
                                                                    
                                                    print(f"DEBUG: 🎯 SKIPPED normal embedding for report tool '{tool_name}' (using RAG instead)")
                                                    
                                                except Exception as e:
                                                    print(f"DEBUG: ❌ ERROR auto-embedding report: {e}")
                                                    import traceback
                                                    traceback.print_exc()
                                                    # Graceful degradation - continue without embedding
                                            
                                            else:
                                                # Normal tools: use standard embedding
                                                print(f"DEBUG: Using normal embedding for non-report tool '{tool_name}'")
                                                memory_store.add_tool_execution(
                                                    session_id=session_id,
                                                    tool_name=tool_name,
                                                    tool_args=tool_args,
                                                    tool_output=raw_output
                                                )
                                        except Exception as e:
                                            print(f"DEBUG: Error storing custom tool: {e}")
                                    
                                    # Stream result
                                    preview = raw_output[:100] + "..." if len(raw_output) > 100 else raw_output
                                    yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': preview})}\n\n"
                                    await asyncio.sleep(0)
                                    
                                    last_intent = "custom_tool"
                                    if json_resp is not None:
                                        last_data = json_resp
                                    else:
                                        last_data = {"output": raw_output}
                                    
                                    continue
                                except Exception as e:
                                    current_context_text += f"\nSystem: Error executing custom tool {tool_name}: {str(e)}\n"
                                    continue
                            
                            current_context_text += f"\nSystem: Error - Tool '{tool_name}' not found.\n"
                            continue

                        # MCP Tools
                        agent_name = tool_router[tool_name]
                        session = agent_sessions[agent_name]
                        
                        try:
                            result = await session.call_tool(tool_name, tool_args)
                            raw_output = result.content[0].text
                            
                            # Debug logging for result
                            print(f"\n{'='*60}")
                            print(f"TOOL RESULT: {tool_name}")
                            print(f"OUTPUT: {raw_output[:500]}{'...' if len(raw_output) > 500 else ''}")
                            print(f"{'='*60}\n")
                            
                            try:
                                parsed = json.loads(raw_output)
                                if "error" in parsed and parsed["error"] == "auth_required":
                                    yield f"data: {json.dumps({'type': 'response', 'content': 'Authentication required.', 'intent': 'request_auth', 'data': parsed})}\n\n"
                                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                    return
                                
                                if tool_name == "get_recent_emails_content" and isinstance(parsed, dict) and "emails" in parsed:
                                    emails = parsed.get("emails", [])
                                    email_texts = [f"Email {i+1}:\nSubject: {e.get('subject', 'N/A')}\nFrom: {e.get('from', 'N/A')}\nDate: {e.get('date', 'N/A')}\nBody: {e.get('body', 'N/A')}" for i, e in enumerate(emails)]
                                    raw_output = f"Here is the content of the {len(emails)} emails found. FAST AND CONCISELY Summarize them:\n" + "\n".join(email_texts)
                                
                                if tool_name.startswith("list_") or tool_name.startswith("read_") or tool_name.startswith("create_") or tool_name == "draft_email" or tool_name == "send_email" or tool_name == "get_recent_emails_content":
                                    last_intent = tool_name
                                    if tool_name == "list_upcoming_events":
                                        last_intent = "list_events"
                                    if tool_name == "get_recent_emails_content":
                                        last_intent = "list_emails"
                                    last_data = parsed

                                if tool_name == "search_web":
                                    last_intent = "search_web"
                                    last_data = parsed

                                if tool_name == "collect_data":
                                    last_intent = "collect_data"
                                    last_data = parsed

                            except:
                                pass

                            display_output = raw_output[:50000] + "...(truncated)" if len(raw_output) > 50000 else raw_output
                            current_context_text += f"\nTool '{tool_name}' Output: {display_output}\n"
                            
                            _extract_and_persist_ids(session_id, tool_name, raw_output)
                            
                            if memory_store:
                                try:
                                    memory_store.add_tool_execution(
                                        session_id=session_id,
                                        tool_name=tool_name,
                                        tool_args=tool_args,
                                        tool_output=raw_output
                                    )
                                except Exception as e:
                                    print(f"DEBUG: Error storing tool execution: {e}")
                            
                            # Stream result
                            preview = display_output[:100] + "..." if len(display_output) > 100 else display_output
                            yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': preview})}\n\n"
                            await asyncio.sleep(0)
                            
                            tools_used_summary.append(f"{tool_name}: {display_output[:500]}...")
                        except Exception as e:
                            current_context_text += f"\nSystem: Error executing tool {tool_name}: {str(e)}\n"
                    
                    else:
                        # No tool call, this is the final answer
                        print(f"[DEBUG] No tool call detected. Treating as final answer.")
                        print(f"[DEBUG] tool_call value: {tool_call}")
                        print(f"[DEBUG] Final response: {llm_output[:200]}...")
                        final_response = llm_output
                        break
                
                if not final_response:
                    final_response = "I completed the requested actions."

            # Save to memory
            if memory_store and final_response:
                memory_store.add_memory("user", user_message, metadata={"session_id": session_id})
                memory_store.add_memory("assistant", final_response, metadata={"session_id": session_id})
            
            # Save to short-term history
            _get_conversation_history(session_id).append({
                "user": user_message,
                "assistant": final_response,
                "tools": tools_used_summary
            })
            
            # Stream final response
            yield f"data: {json.dumps({'type': 'response', 'content': final_response, 'intent': last_intent, 'data': last_data, 'tool_name': tool_name})}\n\n"
            await asyncio.sleep(0)
            
            # Stream done event
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            print(f"ERROR in SSE stream: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
