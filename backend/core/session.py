"""
Session and conversation state management.
Extracted from server.py for better readability.
"""
import json
from typing import Any
from collections import deque

from core.models import ChatRequest


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
    # Import here to avoid circular imports - memory_store is set at runtime
    from core.server import memory_store
    
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
