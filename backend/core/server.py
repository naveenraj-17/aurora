import os
import sys
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:
    from core.memory import MemoryStore
except ImportError:
    print("Warning: MemoryStore dependencies not found. Memory disabled.")
    MemoryStore = None

from core.mcp_client import MCPClientManager
from core.config import load_settings
from core.routes.settings import _init_memory_store

# Route routers
from core.routes.auth import router as auth_router
from core.routes.settings import router as settings_router
from core.routes.agents import router as agents_router
from core.routes.tools import router as tools_router
from core.routes.n8n import router as n8n_router
from core.routes.data import router as data_router
from core.routes.chat import router as chat_router

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = "llama3"

# Agent Configuration
AGENTS = {
    # "gmail": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "gmail.py"),
    "time": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "time.py"),
    # "drive": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "drive.py"),
    # "calendar": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "calendar_agent.py"),
    "local_file_agent": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "local_file.py"),
    "browser": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "browser.py"),
    "sql": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "sql_agent.py"),
    "maps": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "map_details.py"),
    "personal_details": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "personal_details.py"),
    "collect_data": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "collect_data.py"),
    "pdf_parser": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "pdf_parser.py"),
    "xlsx_parser": os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "xlsx_parser.py"),
}

# Global variables
agent_sessions: dict[str, ClientSession] = {}  # Map of client_name -> session
tool_router: dict[str, str] = {}                # Map of tool_name -> client_name
exit_stack = None
memory_store = None
mcp_manager: Optional[MCPClientManager] = None

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

# --- Include Route Routers ---
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(tools_router)
app.include_router(n8n_router)
app.include_router(data_router)
app.include_router(chat_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
