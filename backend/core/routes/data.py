"""
Synthetic data, models, bedrock, config, history endpoints.
"""
import os
import json
import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException
import httpx

from core.config import load_settings
from core.llm_providers import _make_aws_client, OLLAMA_BASE_URL
from core.session import conversation_histories, session_state
from services.synthetic_data import generate_synthetic_data, SyntheticDataRequest, current_job, DATASETS_DIR

router = APIRouter()


# --- Synthetic Data ---

@router.post("/api/synthetic/generate")
async def start_synthetic_generation(req: SyntheticDataRequest):
    if current_job["status"] == "generating":
        raise HTTPException(status_code=400, detail="A generation job is already running.")

    asyncio.create_task(generate_synthetic_data(req))
    return {"status": "started", "message": "Generation started in background."}


@router.get("/api/synthetic/status")
async def get_synthetic_status():
    return current_job


@router.get("/api/synthetic/datasets")
async def list_datasets():
    if not os.path.exists(DATASETS_DIR):
        return []
    files = [f for f in os.listdir(DATASETS_DIR) if f.endswith(".jsonl")]
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


# --- Models ---

@router.get("/api/models")
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

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if response.status_code == 200:
                local_models = [m["name"] for m in response.json().get("models", [])]
    except Exception as e:
        print(f"Error fetching models: {e}")
        local_models = ["mistral", "llama3"]

    return {"local": local_models, "cloud": cloud_models}


@router.get("/api/bedrock/models")
async def get_bedrock_models():
    """Lists Bedrock foundation models."""
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
        print(f"Error listing Bedrock models: {e}")
        return {
            "models": [],
            "error": "Unable to list Bedrock models. Check AWS credentials/permissions and region.",
        }


@router.get("/api/bedrock/inference-profiles")
async def get_bedrock_inference_profiles():
    """Lists Bedrock inference profiles."""
    settings = load_settings()
    region = (settings.get("aws_region") or "us-east-1").strip() or "us-east-1"

    def _list_profiles_sync():
        client = _make_aws_client("bedrock", region, settings)

        if not hasattr(client, "list_inference_profiles"):
            return []

        resp = client.list_inference_profiles()
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


# --- History Management ---

@router.delete("/api/history/recent")
async def clear_recent_history():
    """Clears the short-term in-memory session history."""
    conversation_histories.clear()
    session_state.clear()
    return {"status": "success", "message": "Recent session history (all sessions) cleared."}


@router.delete("/api/history/all")
async def clear_all_history():
    """Clears BOTH short-term session history AND long-term ChromaDB memory."""
    import core.server as _server

    conversation_histories.clear()
    session_state.clear()
    if _server.memory_store:
        success = _server.memory_store.clear_memory()
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear long-term memory.")
    return {"status": "success", "message": "All history (Recent + Long-term) cleared."}
