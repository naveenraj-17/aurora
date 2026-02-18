
import pytest
from fastapi.testclient import TestClient
import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))

from main import app
from core.server import agent_sessions

def test_get_available_tools():
    # Use context manager to trigger startup lifespan events
    with TestClient(app) as client:
        # Startup has run. Now we can inject our mock into the global dictionary.
        
        mock_session = MagicMock()
        # The endpoint expects an object with a .tools attribute that is a list of tools
        # defined as Pydantic models or objects with name, description, inputSchema attributes
        
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.inputSchema = {"type": "object"}
        
        mock_result = MagicMock()
        mock_result.tools = [mock_tool]
        
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        
        # Inject mock session
        agent_sessions["test_agent"] = mock_session
        
        response = client.get("/api/tools/available")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        
        print(f"\nDEBUG: Returned tools: {[t['name'] for t in data['tools']]}")
        
        # Check if our test tool is present
        tools = data["tools"]
        found = False
        for t in tools:
            if t["name"] == "test_tool":
                found = True
                assert t["source"] == "test_agent"
                assert t["type"] == "mcp_native"
                break
                
        assert found, "Test tool not found in response"
        print("✅ /api/tools/available returned expected structure and content")

if __name__ == "__main__":
    try:
        test_get_available_tools()
        print("ALL TESTS PASSED")
    except Exception as e:
        print(f"TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
