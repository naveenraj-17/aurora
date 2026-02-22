"""
Pydantic models and data classes used across the backend.
Extracted from server.py for better readability.
"""
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    # Client-generated ID for scoping short-term context. Frontend should generate a new
    # one on each reload so each tab/reload is a fresh session.
    session_id: str | None = None
    # The active agent ID — sent by the frontend on every request so the backend
    # doesn't rely on the global variable (which resets on uvicorn reload).
    agent_id: str | None = None
    # Optional ephemeral client-side state we want the server/agent to reuse.
    client_state: dict[str, Any] | None = None

class ChatResponse(BaseModel):
    response: str
    intent: str = "chat" # chat, list_emails, render_email, list_files, list_events, request_auth, list_local_files, render_local_file
    data: Any | None = None
    tool_name: str | None = None


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


class AddMCPServerRequest(BaseModel):
    name: str
    command: str
    args: List[str] = []
    env: Dict[str, str] = {}


class GoogleCredsRequest(BaseModel):
    content: str # Raw JSON string or dict
