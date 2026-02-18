"""
Tool definitions, aggregation, and system prompt construction.
Extracted from server.py to eliminate duplication between chat() and chat_stream().
"""
import json
import time
import datetime
import zoneinfo


# System Prompt for Native Tool Calling (Personal Assistant)
NATIVE_TOOL_SYSTEM_PROMPT = """You are a highly capable Personal Intelligent Assistant.
Your mission is to assist the user with everyday tasks, managing emails, scheduling, retrieving personal information, and utilizing provided tools to make their life easier.

### CURRENT DATE & TIME CONTEXT
**Current Date:** {current_date}
**Current Time:** {current_time}
**Timezone:** {timezone}

**IMPORTANT:** When tools return dates or timestamps, DO NOT add your own temporal context. Simply present the date/time returned by the tool. If you need to calculate relative time, use the appropriate tool or state the exact difference in days/weeks/months by doing simple math with the current date above.

### CORE OPERATING RULES
1.  **Think Step-by-Step:** Before calling a tool, briefly analyze the user's request. Determine if you need to fetch a list (e.g., recent emails) before you can act on a specific item.
2.  **Accuracy First:** Never guess IDs. Always use `list_` or `search_` tools to find the real ID first.
3.  **Privacy and Security:** You are operating in a personal environment. Handle personal data with care.

### TOOL USAGE PROTOCOL
*   **Listing vs. Acting:** If the user says "Reply to the last email from John", you MUST first call `list_emails` or `search_emails` to get the correct email ID. You cannot action a "concept".
*   **Parameters:**
    *   `limit`: Default to 5 unless specified (e.g., "all").
    *   `query`: Convert natural language to appropriate search terms.

### TOOLS
You have access to the following tools:
{tools_json}

### RESPONSE STYLE
*   **Friendly & Helpful:** Be conversational but concise.
*   **Action-Oriented:** If a task is done, let the user know. If data is retrieved, present it clearly.
"""


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


class VirtualTool:
    """A lightweight tool descriptor that mimics the shape of an MCP tool."""
    def __init__(self, name, description, inputSchema):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


def build_virtual_tools():
    """
    Build the list of infrastructure-level virtual tools that are always available.
    Returns a list of VirtualTool instances.
    """
    tools = []
    
    # Internal tool: on-demand long-term memory retrieval
    tools.append(VirtualTool(
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
    ))
    
    # Internal tool: Current Session Context
    tools.append(VirtualTool(
        "get_current_session_context",
        "Get valid IDs (email_id, event_id, etc.) and location from the current active session state.",
        {"type": "object", "properties": {}, "required": []}
    ))
    
    # Internal tool: Clear Session Context
    tools.append(VirtualTool(
        "clear_session_context",
        "Clear session state to start a fresh flow. Call this when you detect the user wants to start a NEW task "
        "or operation (e.g., 'start a new email', 'different event', 'start over'). "
        "Scope: 'transient' (default - clear IDs but keep general context), 'all' (clear everything), 'ids_only' (clear only ID fields).",
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
    ))
    
    # RAG Decision Tool
    tools.append(VirtualTool(
        "decide_search_or_analyze",
        "**INTERNAL**: Decide whether to search embeddings or directly analyze data. "
        "Data is ALREADY embedded after execution - this just determines the approach. "
        "\n\n**Use search_embedded_report when:**"
        "\n- Vague queries: 'concerning patterns', 'unusual behavior'"
        "\n- Correlation: 'frequent contacts', 'similar events'"
        "\n- Large datasets (>100 items) with open-ended questions"
        "\n\n**Use direct analysis when:**"
        "\n- Specific: 'How many?', 'Show John', 'Total emails'"
        "\n- Counting/filtering/summarization"
        "\n\n**Note:** Data is already in current context AND embedded. Choose fastest approach.",
        {
            "type": "object",
            "properties": {
                "user_query": {"type": "string", "description": "The user's question about the data"},
                "report_size": {"type": "integer", "description": "Number of items in the data"},
                "query_type": {"type": "string", "enum": ["exploratory", "specific"], "description": "Query classification"}
            },
            "required": ["user_query", "report_size"]
        }
    ))
    
    # Search Embedded Report Tool
    tools.append(VirtualTool(
        "search_embedded_report",
        "Search the automatically-embedded data semantically. Use for vague/exploratory queries about data patterns.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "n_results": {"type": "integer", "default": 3, "description": "Max chunks to return"}
            },
            "required": ["query"]
        }
    ))
    
    return tools


async def aggregate_all_tools(agent_sessions, active_agent, custom_tools_list):
    """
    Aggregate all available tools: MCP tools + virtual tools + custom tools.
    
    Returns:
        tuple: (all_tools, tool_schema_map, ollama_tools, tools_json)
    """
    all_tools = []
    tool_schema_map = {}  # name -> inputSchema
    
    allowed_tools = active_agent.get("tools", ["all"])
    
    # CRITICAL: Auto-inject RAG tools for ANY analysis agent
    if active_agent.get("type") == "analysis":
        if "decide_search_or_analyze" not in allowed_tools:
            allowed_tools.append("decide_search_or_analyze")
        if "search_embedded_report" not in allowed_tools:
            allowed_tools.append("search_embedded_report")
            
    # CRITICAL: Auto-inject collect_data tool for ALL agents
    if "collect_data" not in allowed_tools:
        allowed_tools.append("collect_data")
    
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

    # Virtual infrastructure tools (always available)
    virtual_tools = build_virtual_tools()
    for vt in virtual_tools:
        all_tools.append(vt)
        tool_schema_map[vt.name] = vt.inputSchema
    
    # Dynamic Custom Tools (n8n/Webhook)
    for ct in custom_tools_list:
        if "all" in allowed_tools or ct['name'] in allowed_tools:
            vt = VirtualTool(ct['name'], ct['description'], ct['inputSchema'])
            all_tools.append(vt)
            tool_schema_map[vt.name] = vt.inputSchema

    # Build Ollama-formatted tools list
    ollama_tools = [
        {
            'type': 'function',
            'function': {
                'name': t.name,
                'description': t.description,
                'parameters': t.inputSchema
            }
        }
        for t in all_tools
    ]
    
    # String version for cloud models (system prompt injection)
    tools_json = str([
        {'tool': t.name, 'description': t.description, 'schema': t.inputSchema}
        for t in all_tools
    ])

    # Debug: Log exactly which tools will be visible to the LLM
    tool_names_for_llm = [t.name for t in all_tools]
    print(f"DEBUG: 🔧 Tools sent to LLM ({len(tool_names_for_llm)}): {tool_names_for_llm}")

    return all_tools, tool_schema_map, ollama_tools, tools_json, allowed_tools


def build_system_prompt(agent_system_template, tools_json, session_id, session_state_getter, memory_store, agent_id=None):
    """
    Construct the final system prompt with tool info, date/time, session context, 
    and recent tool outputs injected.
    
    Args:
        agent_system_template: The base system prompt template (may contain {tools_json} etc.)
        tools_json: String representation of available tools
        session_id: Current session ID
        session_state_getter: Function that returns session state dict for a session_id
        memory_store: Memory store instance (or None)
        agent_id: Optional agent ID for scoping memory queries
    
    Returns:
        str: The fully constructed system prompt
    """
    # Get current date/time for context injection
    now = datetime.datetime.now(zoneinfo.ZoneInfo("UTC"))
    current_date = now.strftime("%B %d, %Y")
    current_time = now.strftime("%I:%M %p")
    timezone = "UTC"
    
    # Inject tools, date/time, and instructions into the template
    system_prompt_text = agent_system_template.replace("{tools_json}", tools_json + TOOL_USAGE_INSTRUCTION)
    system_prompt_text = system_prompt_text.replace("{current_date}", current_date)
    system_prompt_text = system_prompt_text.replace("{current_time}", current_time)
    system_prompt_text = system_prompt_text.replace("{timezone}", timezone)
    
    # --- DYNAMIC RAG INJECTION ---
    # If we have active embeddings, force the LLM to know about them
    try:
        ss = session_state_getter(session_id)
        last_report = ss.get("last_report_context")
        if last_report and (time.time() - last_report.get("timestamp", 0) < 600):  # 10 mins validity
            rag_context_msg = f"""
### ACTIVE RAG CONTEXT (AUTOMATICALLY INJECTED)
You have {last_report.get('row_count', 'some')} items of '{last_report.get('type', 'data')}' embedded in memory (generated {int(time.time() - last_report.get('timestamp', 0))}s ago).

**HOW TO ANSWER QUESTIONS ABOUT THIS DATA:**
1. **AGGREGATION QUESTIONS** (totals, averages, counts, min/max): If a SUMMARY with `numeric_aggregations` is in the tool output above, use those pre-computed values directly. They are accurate.
2. **SPECIFIC LOOKUPS** (e.g., "email from John", "meeting tomorrow", "flight details"): Call `search_embedded_report` with a descriptive query. The full data is embedded in RAG memory.
3. **PATTERN/TREND QUESTIONS** (e.g., "frequent topics", "common contacts"): Call `search_embedded_report` with the pattern description.
4. **DO NOT RE-RUN TOOL FOR EXISTING DATA:** The data is already here. Only call tools if the user explicitly asks for NEW/DIFFERENT data (e.g., "refresh", "different date", "different query").
"""
            system_prompt_text += rag_context_msg
            print(f"DEBUG: 💉 Injected RAG context into system prompt")
    except Exception as e:
        print(f"DEBUG: Error injecting RAG prompt: {e}")
    
    # --- INJECT SESSION CONTEXT ---
    active_ss = session_state_getter(session_id)
    if active_ss:
        valid_context = {k: v for k, v in active_ss.items() if v}
        if valid_context:
            context_str = json.dumps(valid_context, indent=2)
            system_prompt_text += f"\n\n### CURRENT SESSION CONTEXT ###\nThe following variables are active in the current session. You can use these values for tool arguments (e.g., email_id) without asking the user:\n{context_str}\n"
    
    # --- INJECT RECENT TOOL OUTPUTS ---
    if memory_store:
        try:
            recent_tools = memory_store.get_session_tool_outputs(
                session_id=session_id,
                n_results=5,
                agent_id=agent_id
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
- User: "Now draft a new email" (after responding to one) → clear_session_context(scope="transient")
- User: "Check a different date" → clear_session_context(scope="ids_only")  
- User: "Start over" → clear_session_context(scope="all")
"""
        except Exception as e:
            print(f"DEBUG: Error injecting tool history: {e}")
    
    return system_prompt_text
