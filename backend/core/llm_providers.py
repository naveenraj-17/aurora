"""
LLM provider API callers (OpenAI, Anthropic, Gemini, Bedrock, Ollama).
Extracted from server.py to eliminate duplication between chat() and chat_stream().
"""
import os
import json
import asyncio
import httpx
import boto3
from botocore.config import Config


# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = "llama3"


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
        if "on-demand throughput isn't supported" in message or "on-demand throughput isn't supported" in message:
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
        if "on-demand throughput isn't supported" in message or "on-demand throughput isn't supported" in message:
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
    mode,
    current_model,
    current_settings,
    tools=None,
    history_messages=None,
    memory_context_text: str = "",
):
    """
    Unified LLM dispatch function. Routes to the appropriate provider
    based on mode and current_model.
    """
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
