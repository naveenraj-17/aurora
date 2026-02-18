"""
Agent management endpoints (CRUD + active agent).
"""
import os
import json

from fastapi import APIRouter, HTTPException

from core.models import Agent, AgentActiveRequest
from core.tools import NATIVE_TOOL_SYSTEM_PROMPT

router = APIRouter()

USER_AGENTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "user_agents.json")

# Module-level state
active_agent_id = "aurora"  # Default


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
        "system_prompt": NATIVE_TOOL_SYSTEM_PROMPT,
        "tools": ["all"]
    }


@router.get("/api/agents")
async def get_agents():
    return load_user_agents()


@router.post("/api/agents")
async def create_agent(agent: Agent):
    agents = load_user_agents()
    # Check if exists
    for i, a in enumerate(agents):
        if a["id"] == agent.id:
            agents[i] = agent.dict()  # Update
            save_user_agents(agents)
            return agent

    agents.append(agent.dict())
    save_user_agents(agents)
    return agent


@router.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if agent_id == "aurora":
        raise HTTPException(status_code=400, detail="Cannot delete default agent.")
    agents = load_user_agents()
    agents = [a for a in agents if a["id"] != agent_id]
    save_user_agents(agents)
    return {"status": "success"}


@router.get("/api/agents/active")
async def get_active_agent_endpoint():
    return {"active_agent_id": active_agent_id}


@router.post("/api/agents/active")
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
