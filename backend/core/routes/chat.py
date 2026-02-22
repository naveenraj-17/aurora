"""
Chat endpoints: /chat and /chat/stream
Core ReAct loop logic for both synchronous and streaming chat.
"""
import os
import sys
import json
import asyncio
import re
import time
import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import httpx

from core.config import load_settings
from core.models import ChatRequest, ChatResponse
from core.session import (
    _get_session_id, _get_conversation_history, _get_session_state,
    _apply_sticky_args, _clear_session_context, _extract_and_persist_ids,
    get_recent_history_messages,
)
from core.llm_providers import generate_response as llm_generate_response
from core.tools import (
    NATIVE_TOOL_SYSTEM_PROMPT,
    aggregate_all_tools,
    build_system_prompt,
)
from core.routes.agents import (
    load_user_agents, get_active_agent_data, active_agent_id,
)
from core.routes.tools import load_custom_tools

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers to access mutable server-level globals without circular imports.
# We lazily import core.server inside each endpoint function body.
# ---------------------------------------------------------------------------

MAX_TURNS = 15  # Maximum ReAct loop iterations
REPORT_CHUNK_SIZE = 50  # Rows per chunk when embedding reports into RAG

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    import core.server as _server
    if not _server.agent_sessions:
        raise HTTPException(status_code=500, detail="No agents connected")

    session_id = _get_session_id(request)
    user_message = request.message

    # Merge client-provided ephemeral state into server session state (best-effort)
    ss = _get_session_state(session_id)
    if request.client_state and isinstance(request.client_state, dict):
        active_facility = request.client_state.get("active_facility_id")
        if active_facility:
            ss["facility_id"] = str(active_facility)
    
    # -- Load Active Agent Logic --
    active_agent = get_active_agent_data()
    agent_system_template = active_agent.get("system_prompt", NATIVE_TOOL_SYSTEM_PROMPT)
    print(f"DEBUG: Using Agent '{active_agent.get('name')}' with tools: {active_agent.get('tools', ['all'])}")

    # 1. Aggregate Tools & Build Schema Map (from core.tools)
    custom_tools = load_custom_tools()
    all_tools, tool_schema_map, ollama_tools, tools_json, allowed_tools = await aggregate_all_tools(
        _server.agent_sessions, active_agent, custom_tools
    )

    # 2. Build System Prompt (from core.tools)
    system_prompt_text = build_system_prompt(
        agent_system_template, tools_json, session_id,
        _get_session_state, _server.memory_store, agent_id=active_agent_id
    )

    current_settings = load_settings()
    current_model = current_settings.get("model", "mistral")
    mode = current_settings.get("mode", "local")

    # LLM caller wrapper — delegates to the shared llm_providers module
    async def generate_response(
        prompt_msg,
        sys_prompt,
        tools=None,
        history_messages=None,
        memory_context_text: str = "",
    ):
        return await llm_generate_response(
            prompt_msg=prompt_msg,
            sys_prompt=sys_prompt,
            mode=mode,
            current_model=current_model,
            current_settings=current_settings,
            tools=tools,
            history_messages=history_messages,
            memory_context_text=memory_context_text,
        )

    # --- ReAct Loop ---
    memory_context = ""
    recent_history_messages = get_recent_history_messages(session_id, agent_id=active_agent_id)
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
            
            # ── SAFETY GUARD: Prevent "prompt too long" errors ──
            MAX_PROMPT_CHARS = 400000  # ~100K tokens
            total_prompt_chars = len(active_prompt) + len(active_sys_prompt) + len(memory_context)
            if total_prompt_chars > MAX_PROMPT_CHARS:
                print(f"⚠️ PROMPT SIZE GUARD: Total ~{total_prompt_chars} chars exceeds {MAX_PROMPT_CHARS} limit. Truncating context.")
                overflow = total_prompt_chars - MAX_PROMPT_CHARS
                active_prompt = active_prompt[:len(active_prompt) - overflow]
                print(f"⚠️ Truncated active_prompt to {len(active_prompt)} chars")
            
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

                # ── EXECUTION GUARD: Block tools not in this agent's allowed list ──
                always_allowed = {
                    "get_current_session_context", "clear_session_context",
                    "query_past_conversations", "decide_search_or_analyze",
                    "search_embedded_report", "embed_report_for_exploration"
                }
                if "all" not in allowed_tools and tool_name not in allowed_tools and tool_name not in always_allowed:
                    block_msg = f"Tool '{tool_name}' is not available for this agent. Available tools: {', '.join(allowed_tools)}. Please use only your available tools."
                    print(f"\n⛔ BLOCKED TOOL CALL: {tool_name} (not in allowed_tools: {allowed_tools})")
                    current_context_text += f"\nSystem: {block_msg}\n"
                    continue

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
                     if _server.memory_store:
                         try:
                             _server.memory_store.add_tool_execution(
                                 session_id=session_id,
                                 tool_name=tool_name,
                                 tool_args={},
                                 tool_output=raw_output,
                                 agent_id=active_agent_id
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
                    if _server.memory_store:
                        try:
                            _server.memory_store.add_tool_execution(
                                session_id=session_id,
                                tool_name=tool_name,
                                tool_args={"scope": scope},
                                tool_output=raw_output,
                                agent_id=active_agent_id
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
                        if _server.memory_store:
                            try:
                                _server.memory_store.add_tool_execution(
                                    session_id=session_id,
                                    tool_name=tool_name,
                                    tool_args=tool_args,
                                    tool_output=raw_output,
                                    agent_id=active_agent_id
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
                        result = _server.memory_store.embed_report_for_session(
                            session_id=session_id,
                            report_data=report_data,
                            report_type=report_type,
                            chunk_size=REPORT_CHUNK_SIZE
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
                        results = _server.memory_store.search_embedded_report(
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

                        if not _server.memory_store:
                            raw_output = json.dumps({"memories": [], "error": "memory_disabled"})
                            current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                            tools_used_summary.append(f"{tool_name}: {raw_output}")
                            last_intent = "memory_query"
                            last_data = {"memories": [], "error": "memory_disabled"}
                            continue

                        where = None
                        if scope == "session":
                            where = {"session_id": session_id}

                        memories = _server.memory_store.query_memory(query, n_results=n_results, where=where)
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
                if tool_name not in _server.tool_router:
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
                                 
                                 
                             # NEW: Extract and persist IDs for custom tools too
                             _extract_and_persist_ids(session_id, tool_name, raw_output)
                             
                             # ── SMART CONTEXT: Report size check ──
                             # For report tools with large output, send a summary to context
                             # instead of the full data (which causes "prompt too big" errors).
                             # The full data is still embedded in RAG for specific lookups.
                             REPORT_SIZE_THRESHOLD = 30000  # ~30KB — safe for most LLM context windows
                             
                             if _server.memory_store:
                                 try:
                                     print(f"DEBUG: Checking tool_type for '{tool_name}': {target_tool.get('tool_type')}")
                                     if target_tool.get("tool_type") == "report":
                                         # Report tools: auto-embed via RAG (skip normal embedding)
                                         print(f"DEBUG: ✅ REPORT TOOL DETECTED - Starting auto-embed for '{tool_name}'")
                                         try:
                                             parsed_output = json.loads(raw_output)
                                             print(f"DEBUG: Parsed report output type: {type(parsed_output)}")
                                             
                                             # Automatically embed each report + build context-safe output
                                             context_safe_reports = []
                                             
                                             if isinstance(parsed_output, list):
                                                 for idx, report_obj in enumerate(parsed_output):
                                                     if isinstance(report_obj, dict) and "data" in report_obj:
                                                         if report_obj.get("is_file"):
                                                             print(f"DEBUG: 📂 Report #{idx+1} is a FILE. Skipping auto-embedding.")
                                                             context_safe_reports.append(report_obj)
                                                             continue
                                                         report_type = report_obj.get("report", "unknown")
                                                         report_data = report_obj.get("data", [])
                                                         
                                                         print(f"DEBUG: 📊 AUTO-EMBEDDING REPORT #{idx+1}: '{report_type}' with {len(report_data)} rows")
                                                         
                                                         embed_result = _server.memory_store.embed_report_for_session(
                                                             session_id=session_id,
                                                             report_data=report_data,
                                                             report_type=report_type,
                                                             chunk_size=REPORT_CHUNK_SIZE
                                                         )
                                                         
                                                         chunks_count = embed_result.get('chunks_embedded', 0)
                                                         print(f"DEBUG: ✅ EMBEDDED {chunks_count} chunks for '{report_type}'")
                                                         
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
                                                         
                                                         # Check if this individual report's data is too large for context
                                                         report_json_size = len(json.dumps(report_obj))
                                                         if report_json_size > REPORT_SIZE_THRESHOLD:
                                                             print(f"DEBUG: 📏 Report '{report_type}' is {report_json_size} chars — TOO LARGE for context. Sending summary instead.")
                                                             summary = _server.memory_store.generate_report_summary(report_data, report_type)
                                                             context_safe_reports.append(summary)
                                                         else:
                                                             print(f"DEBUG: 📏 Report '{report_type}' is {report_json_size} chars — fits in context. Sending full data.")
                                                             context_safe_reports.append(report_obj)
                                                     else:
                                                         context_safe_reports.append(report_obj)
                                                 
                                                 # Replace raw_output with context-safe version
                                                 raw_output = json.dumps(context_safe_reports)
                                                 print(f"DEBUG: 📦 Context-safe output size: {len(raw_output)} chars (threshold: {REPORT_SIZE_THRESHOLD})")
                                             else:
                                                 print(f"DEBUG: ⚠️ Report output is not a list: {type(parsed_output)}")
                                             
                                             print(f"DEBUG: 🎯 SKIPPED normal embedding for report tool '{tool_name}' (using RAG instead)")
                                             
                                         except Exception as e:
                                             print(f"DEBUG: ❌ ERROR auto-embedding report: {e}")
                                             import traceback
                                             traceback.print_exc()
                                     else:
                                         # Normal tools: use standard embedding
                                         print(f"DEBUG: Using normal embedding for non-report tool '{tool_name}'")
                                         _server.memory_store.add_tool_execution(
                                             session_id=session_id,
                                             tool_name=tool_name,
                                             tool_args=tool_args,
                                             tool_output=raw_output,
                                             agent_id=active_agent_id
                                         )
                                 except Exception as e:
                                     print(f"DEBUG: Error storing custom tool in memory: {e}")
                             
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

                # 4. MCP Tools
                agent_name = _server.tool_router[tool_name]
                session = _server.agent_sessions[agent_name]
                
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
                    if _server.memory_store:
                        try:
                            _server.memory_store.add_tool_execution(
                                session_id=session_id,
                                tool_name=tool_name,
                                tool_args=tool_args,
                                tool_output=raw_output,
                                agent_id=active_agent_id
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
    if _server.memory_store and final_response:
        _server.memory_store.add_memory("user", user_message, metadata={"session_id": session_id, "agent_id": active_agent_id})
        _server.memory_store.add_memory("assistant", final_response, metadata={"session_id": session_id, "agent_id": active_agent_id})
        
    # Save to Short-Term History (session-scoped)
    _get_conversation_history(session_id, agent_id=active_agent_id).append({
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

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Real-time streaming endpoint with SSE"""
    print(f"[SSE] Endpoint called with message: {request.message[:50]}...")
    
    async def event_generator():
        import core.server as _server
        try:
            if not _server.agent_sessions:
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
            
            # -- Load Active Agent Logic --
            # Prefer agent_id from the request (sent by frontend) over the global
            # because the global resets on uvicorn reload.
            request_agent_id = request.agent_id
            if request_agent_id:
                agents = load_user_agents()
                active_agent = next((a for a in agents if a["id"] == request_agent_id), None)
                if not active_agent:
                    print(f"⚠️ Agent '{request_agent_id}' from request not found, falling back to global")
                    active_agent = get_active_agent_data()
            else:
                active_agent = get_active_agent_data()

            active_agent_id_for_session = active_agent.get("id", active_agent_id)
            agent_system_template = active_agent.get("system_prompt", NATIVE_TOOL_SYSTEM_PROMPT)
            print(f"DEBUG: 🎯 Active agent: id={active_agent.get('id')}, name={active_agent.get('name')}, allowed_tools={active_agent.get('tools', ['all'])}")

            # 1. Aggregate Tools & Build Schema Map (from core.tools)
            custom_tools = load_custom_tools()
            all_tools, tool_schema_map, ollama_tools, tools_json, allowed_tools = await aggregate_all_tools(
                _server.agent_sessions, active_agent, custom_tools
            )

            # 2. Build System Prompt (from core.tools)
            system_prompt_text = build_system_prompt(
                agent_system_template, tools_json, session_id,
                _get_session_state, _server.memory_store, agent_id=active_agent_id_for_session
            )

            current_settings = load_settings()
            current_model = current_settings.get("model", "mistral")
            mode = current_settings.get("mode", "local")

            # LLM caller wrapper — delegates to the shared llm_providers module
            async def generate_response(
                prompt_msg,
                sys_prompt,
                tools=None,
                history_messages=None,
                memory_context_text: str = "",
            ):
                return await llm_generate_response(
                    prompt_msg=prompt_msg,
                    sys_prompt=sys_prompt,
                    mode=mode,
                    current_model=current_model,
                    current_settings=current_settings,
                    tools=tools,
                    history_messages=history_messages,
                    memory_context_text=memory_context_text,
                )

            # --- ReAct Loop with Streaming ---
            memory_context = ""
            recent_history_messages = get_recent_history_messages(session_id, agent_id=active_agent_id_for_session)
            current_context_text = f"User Request: {user_message}\n"

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
                    
                    # ── SAFETY GUARD: Prevent "prompt too long" errors ──
                    # Estimate total prompt size and truncate if dangerously large.
                    # ~4 chars per token is a conservative estimate.
                    MAX_PROMPT_CHARS = 400000  # ~100K tokens — leaves room for system prompt + response
                    total_prompt_chars = len(active_prompt) + len(active_sys_prompt) + len(memory_context)
                    if total_prompt_chars > MAX_PROMPT_CHARS:
                        print(f"⚠️ PROMPT SIZE GUARD: Total ~{total_prompt_chars} chars exceeds {MAX_PROMPT_CHARS} limit. Truncating context.")
                        # Keep the user request + last tool output, drop middle context
                        overflow = total_prompt_chars - MAX_PROMPT_CHARS
                        active_prompt = active_prompt[:len(active_prompt) - overflow]
                        print(f"⚠️ Truncated active_prompt to {len(active_prompt)} chars")
                    
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
                            # Try parsing the whole string first
                            tool_call = json.loads(cleaned_output)
                        except Exception as e:
                            # Find the first { and decode exactly one JSON object
                            start_idx = cleaned_output.find('{')
                            if start_idx != -1:
                                decoder = json.JSONDecoder()
                                try:
                                    # raw_decode extracts the first valid JSON object and ignores the rest
                                    tool_call, _ = decoder.raw_decode(cleaned_output[start_idx:])
                                except ValueError:
                                    # Fallback to greedy regex method just in case
                                    json_match = re.search(r'\{.*\}', cleaned_output, re.DOTALL)
                                    if json_match:
                                        tool_call = json.loads(json_match.group(0))
                                    else:
                                        raise e
                            else:
                                raise e
                    except Exception as e:
                        json_error = str(e)

                    # Debug: Log raw LLM output
                    print(f"[DEBUG] LLM RAW OUTPUT: {llm_output[:200]}...")
                    print(f"[DEBUG] Parsed tool_call: {tool_call}")
                    
                    if json_error:
                        # Check if the output was actually attempting to be a tool call (contains '{')
                        # If it doesn't contain '{', it's a plain text final response, not an error
                        cleaned_for_check = llm_output.replace("```json", "").replace("```", "").strip()
                        if '{' in cleaned_for_check:
                            # Output looked like JSON but failed to parse — ask LLM to retry
                            print(f"[DEBUG] JSON Parsing Error (malformed JSON): {json_error}")
                            current_context_text += f"\nSystem: JSON Parsing Error: {json_error}. Please Try Again with valid JSON.\n"
                            continue
                        else:
                            # Output is plain text — this IS the final answer, break out
                            print(f"[DEBUG] No JSON detected in output. Treating as final response.")
                            final_response = llm_output
                            break

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

                        # ── EXECUTION GUARD: Block tools not in this agent's allowed list ──
                        # Virtual/internal tools are always permitted
                        always_allowed = {
                            "get_current_session_context", "clear_session_context",
                            "query_past_conversations", "decide_search_or_analyze",
                            "search_embedded_report", "embed_report_for_exploration"
                        }
                        if "all" not in allowed_tools and tool_name not in allowed_tools and tool_name not in always_allowed:
                            block_msg = f"Tool '{tool_name}' is not available for this agent. Available tools: {', '.join(allowed_tools)}. Please use only your available tools."
                            print(f"\n⛔ BLOCKED TOOL CALL: {tool_name} (not in allowed_tools: {allowed_tools})")
                            current_context_text += f"\nSystem: {block_msg}\n"
                            
                            yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'preview': '⛔ Blocked: Tool not available for this agent'})}\n\n"
                            await asyncio.sleep(0)
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
                            
                            if _server.memory_store:
                                try:
                                    _server.memory_store.add_tool_execution(
                                        session_id=session_id,
                                        tool_name=tool_name,
                                        tool_args={},
                                        tool_output=raw_output,
                                        agent_id=active_agent_id_for_session
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
                            
                            if _server.memory_store:
                                try:
                                    _server.memory_store.add_tool_execution(
                                        session_id=session_id,
                                        tool_name=tool_name,
                                        tool_args={"scope": scope},
                                        tool_output=raw_output,
                                        agent_id=active_agent_id_for_session
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
                                
                                result = _server.memory_store.embed_report_for_session(
                                    session_id=session_id,
                                    report_data=report_data,
                                    report_type=report_type,
                                    chunk_size=REPORT_CHUNK_SIZE
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
                                
                                results = _server.memory_store.search_session_embeddings(
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

                                if not _server.memory_store:
                                    raw_output = json.dumps({"memories": [], "error": "memory_disabled"})
                                    current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                    tools_used_summary.append(f"{tool_name}: {raw_output}")
                                    last_intent = "memory_query"
                                    last_data = {"memories": [], "error": "memory_disabled"}
                                    continue

                                where = None
                                if scope == "session":
                                    where = {"session_id": session_id}

                                memories = _server.memory_store.query_memory(query, n_results=n_results, where=where)
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
                                results = _server.memory_store.search_embedded_report(
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
                        if tool_name not in _server.tool_router:
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
                                    
                                    _extract_and_persist_ids(session_id, tool_name, raw_output)
                                    
                                    # ── SMART CONTEXT: Report size check (STREAMING) ──
                                    REPORT_SIZE_THRESHOLD = 30000  # ~30KB
                                    
                                    if _server.memory_store:
                                        try:
                                            # Check for report tool (RAG auto-embed)
                                            print(f"DEBUG: Checking tool_type for '{tool_name}': {target_tool.get('tool_type')}")
                                            
                                            if target_tool.get("tool_type") == "report":
                                                # Report tools: auto-embed via RAG (skip normal embedding)
                                                print(f"DEBUG: ✅ REPORT TOOL DETECTED (STREAM) - Starting auto-embed for '{tool_name}'")
                                                try:
                                                    parsed_output = json.loads(raw_output)
                                                    print(f"DEBUG: Parsed report output type: {type(parsed_output)}")
                                                    
                                                    # Automatically embed each report + build context-safe output
                                                    context_safe_reports = []
                                                    
                                                    if isinstance(parsed_output, list):
                                                        for idx, report_obj in enumerate(parsed_output):
                                                            if isinstance(report_obj, dict) and "data" in report_obj:
                                                                if report_obj.get("is_file"):
                                                                    print(f"DEBUG: 📂 Report #{idx+1} is a FILE. Skipping auto-embedding.")
                                                                    context_safe_reports.append(report_obj)
                                                                    continue
                                                                report_type = report_obj.get("report", "unknown")
                                                                report_data = report_obj.get("data", [])
                                                                
                                                                print(f"DEBUG: 📊 AUTO-EMBEDDING REPORT #{idx+1}: '{report_type}' with {len(report_data)} rows")
                                                                
                                                                embed_result = _server.memory_store.embed_report_for_session(
                                                                    session_id=session_id,
                                                                    report_data=report_data,
                                                                    report_type=report_type,
                                                                    chunk_size=REPORT_CHUNK_SIZE
                                                                )
                                                                
                                                                chunks_count = embed_result.get('chunks_embedded', 0)
                                                                print(f"DEBUG: ✅ EMBEDDED {chunks_count} chunks for '{report_type}'")
                                                                
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
                                                                
                                                                # Check if this report is too large for context
                                                                report_json_size = len(json.dumps(report_obj))
                                                                if report_json_size > REPORT_SIZE_THRESHOLD:
                                                                    print(f"DEBUG: 📏 Report '{report_type}' is {report_json_size} chars — TOO LARGE for context. Sending summary instead.")
                                                                    summary = _server.memory_store.generate_report_summary(report_data, report_type)
                                                                    context_safe_reports.append(summary)
                                                                else:
                                                                    print(f"DEBUG: 📏 Report '{report_type}' is {report_json_size} chars — fits in context. Sending full data.")
                                                                    context_safe_reports.append(report_obj)
                                                            else:
                                                                context_safe_reports.append(report_obj)
                                                        
                                                        # Replace raw_output with context-safe version
                                                        raw_output = json.dumps(context_safe_reports)
                                                        print(f"DEBUG: 📦 Context-safe output size: {len(raw_output)} chars (threshold: {REPORT_SIZE_THRESHOLD})")
                                                    
                                                    print(f"DEBUG: 🎯 SKIPPED normal embedding for report tool '{tool_name}' (using RAG instead)")
                                                    
                                                except Exception as e:
                                                    print(f"DEBUG: ❌ ERROR auto-embedding report: {e}")
                                                    import traceback
                                                    traceback.print_exc()
                                            
                                            else:
                                                # Normal tools: use standard embedding
                                                print(f"DEBUG: Using normal embedding for non-report tool '{tool_name}'")
                                                _server.memory_store.add_tool_execution(
                                                    session_id=session_id,
                                                    tool_name=tool_name,
                                                    tool_args=tool_args,
                                                    tool_output=raw_output,
                                                    agent_id=active_agent_id_for_session
                                                )
                                        except Exception as e:
                                            print(f"DEBUG: Error storing custom tool: {e}")
                                    
                                    current_context_text += f"\nTool '{tool_name}' Output: {raw_output}\n"
                                    tools_used_summary.append(f"{tool_name}: {raw_output[:500]}...")
                                    
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
                        agent_name = _server.tool_router[tool_name]
                        session = _server.agent_sessions[agent_name]
                        
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
                            
                            if _server.memory_store:
                                try:
                                    _server.memory_store.add_tool_execution(
                                        session_id=session_id,
                                        tool_name=tool_name,
                                        tool_args=tool_args,
                                        tool_output=raw_output,
                                        agent_id=active_agent_id_for_session
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
            if _server.memory_store and final_response:
                _server.memory_store.add_memory("user", user_message, metadata={"session_id": session_id, "agent_id": active_agent_id_for_session})
                _server.memory_store.add_memory("assistant", final_response, metadata={"session_id": session_id, "agent_id": active_agent_id_for_session})
            
            # Save to short-term history
            _get_conversation_history(session_id, agent_id=active_agent_id_for_session).append({
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

