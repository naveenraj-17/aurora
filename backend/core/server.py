import os
import sys
import asyncio
import json
from typing import Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import httpx
import boto3
from services.google import get_auth_url, finish_auth
from services.synthetic_data import generate_synthetic_data, SyntheticDataRequest, current_job, DATASETS_DIR
from datetime import datetime
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
    "sql": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "sql_agent.py"),
}

class ChatRequest(BaseModel):
    message: str

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

from collections import deque
conversation_history = deque(maxlen=10) # Keep last 10 turns

# System Prompt for Native Tool Calling (Enterprise/Business Focused)
NATIVE_TOOL_SYSTEM_PROMPT = """You are the Enterprise Business Intelligence Agent for a SaaS Platform.
Your mission is to assist managers, executives, and developers by retrieving accurate data, managing system operations, and explaining technical documentation.

### CORE OPERATING RULES
1.  **Think Step-by-Step:** Before calling a tool, briefly analyze the user's request. Determine if you need to fetch a list (IDs) before you can act on a specific item.
2.  **Accuracy First:** Never guess IDs (e.g., `unit_123`, `email_999`). Always use `list_` or `search_` tools to find the real ID first.
3.  **Data Integrity:** When summarizing data (revenue, counts), be precise. Do not round numbers unless asked.
4.  **Security:** You are operating in a secure environment. You can access internal APIs and Databases via provided tools.

### TOOL USAGE PROTOCOL
*   **Listing vs. Acting:** If the user says "Email the last user", you MUST first call `list_users` or `get_recent_...` to get the email address. You cannot email a "concept".
*   **Parameters:**
    *   `limit`: Default to 5 unless specified (e.g., "all" -> 100).
    *   `query`: Convert natural language to search terms (e.g., "urgent" -> "is:urgent").

### RESPONSE STYLE
*   **Business Professional:** Be concise. No fluff.
*   **Action-Oriented:** If a task is done, say it. If data is retrieved, present it clearly (tables/lists).
"""

def get_recent_history_messages():
    """Returns a list of message dicts for the chat API."""
    messages = []
    for turn in conversation_history:
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

# --- Agent Management Logic ---
class Agent(BaseModel):
    id: str
    name: str
    description: str
    avatar: str = "default"
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
    show_browser: bool = False


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
    return load_settings()

@app.post("/api/settings")
async def update_settings(settings: Settings):
    print(f"DEBUG: update_settings called with: {settings.dict()}")
    data = settings.dict()
    save_settings(data)

    # Reinitialize memory so embeddings provider matches the new mode.
    global memory_store
    if MemoryStore:
        try:
            memory_store = _init_memory_store(data)
        except Exception as e:
            print(f"Warning: failed to reinitialize MemoryStore after settings update: {e}")
    return data


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

    # Dynamic Custom Tools (n8n/Webhook)
    custom_tools = load_custom_tools()
    # We map custom tools to a simplified object that looks like an MCP tool
    class VirtualTool:
        def __init__(self, name, description, inputSchema):
            self.name = name
            self.description = description
            self.inputSchema = inputSchema
    
    for ct in custom_tools:
        # If 'all' or explicitly listed
        if "all" in allowed_tools or ct['name'] in allowed_tools:
             all_tools.append(VirtualTool(ct['name'], ct['description'], ct['inputSchema']))

    # 2. System Prompt
    # Prepare tools for Ollama Native API (List of dicts)
    ollama_tools = [{'type': 'function', 'function': {'name': t.name, 'description': t.description, 'parameters': t.inputSchema}} for t in all_tools]
    
    # Keep the string version for Cloud models (System Prompt injection)
    tools_json = str([{'name': t.name, 'description': t.description, 'schema': t.inputSchema} for t in all_tools])
    
    TOOL_USAGE_INSTRUCTION = """
    
    ### RESPONSE FORMAT INSTRUCTIONS
    If you need to use a specific tool from the list above, you MUST respond with **ONLY** a valid JSON object in the following format:
    { "tool": "tool_name", "arguments": { "key": "value" } }
    
    Do NOT output any other text or markdown when calling a tool.
    If you do not need to use a tool, reply in plain text.
    """
    
    # Inject tools and instructions into the template
    system_prompt_text = agent_system_template.replace("{tools_json}", tools_json + TOOL_USAGE_INSTRUCTION)


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
    MAX_TURNS = 5
    
    # 3. Retrieve Memory
    relevant_memories = []
    if memory_store:
        relevant_memories = memory_store.query_memory(user_message)
    
    memory_context = ""
    if relevant_memories:
        # Keep this as non-instructional context that the model can use as facts.
        memory_context = "Relevant Past Conversations (long-term memory, use as context):\n" + "\n".join(relevant_memories)

    # 4. Inject Short-Term History
    # 4. Inject Short-Term History
    recent_history_messages = get_recent_history_messages()
    
    # Context for LLM (Text-based Fallback for non-native logic or logging)
    # We still keep a text version for "current_context" used in loop logic if needed, 
    # but the API call will use the structured messages.
    
    # current_context is mainly strictly for the 'legacy/text' based prompt construction if we fell back,
    # OR for the internal logic loop to append tool outputs.
    # For the INITIAL prompt, we use the user_message.
    
    current_context_text = f"User Request: {user_message}\n" 
    
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
                print(f"DEBUG: EXTRACTED TOOL ARGS: {tool_name} -> {tool_args}")
                
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
                             except:
                                 raw_output = resp.text
                                 
                                 
                             current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                             tools_used_summary.append(f"{tool_name}: {raw_output[:500]}...")
                             
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

                # Loop Guard with Repetition Tolerance
                current_tool_signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                
                # Increment count
                tool_repetition_counts[current_tool_signature] = tool_repetition_counts.get(current_tool_signature, 0) + 1
                
                if tool_repetition_counts[current_tool_signature] > 1: # Strict: Block 2nd identical call.
                    print(f"DEBUG: Loop detected (>1 call). Identical tool call {tool_name}. Warning LLM.", file=sys.stderr)
                    current_context_text += f"\nSystem: You just called '{tool_name}' with these exact arguments and received results. **STOP**. Do not call it again. Summarize the results you already have.\n"
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
                    current_context_text += f"\nTool '{tool_name}' Output: {display_output}\n"
                    
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
        data=last_data,
        tool_name=tool_name
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
