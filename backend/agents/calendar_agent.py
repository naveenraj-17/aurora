from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import json
from services.google import get_calendar_service, UnauthenticatedError
import datetime

# Initialize MCP Server
app = Server("calendar-mcp-server")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_upcoming_events",
            description="List upcoming calendar events. Returns summary, start time, and htmlLink.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of events to return (default 5)",
                        "default": 5
                    }
                }
            }
        ),
        types.Tool(
            name="create_event",
            description="Create a new calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title"},
                    "start_time": {"type": "string", "description": "Start time in ISO format (e.g. 2024-01-01T10:00:00Z)"},
                    "end_time": {"type": "string", "description": "End time in ISO format"},
                    "description": {"type": "string", "description": "Optional description"}
                },
                "required": ["summary", "start_time", "end_time"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    try:
        service = get_calendar_service()
        
        if name == "list_upcoming_events":
            limit = arguments.get("limit", 5)
            # ... existing implementation ...
            now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
            events_result = service.events().list(
                calendarId='primary', timeMin=now,
                maxResults=limit, singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            
            # Simplify event objects
            simplified_events = []
            for event in events:
                simplified_events.append({
                    "id": event.get("id"),
                    "summary": event.get("summary", "No Title"),
                    "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date")),
                    "headmlLink": event.get("htmlLink")
                })
            
            return [types.TextContent(type="text", text=json.dumps({"events": simplified_events}))]

        elif name == "create_event":
            summary = arguments.get("summary")
            start_time = arguments.get("start_time")
            end_time = arguments.get("end_time")
            description = arguments.get("description", "")
            
            event = {
                'summary': summary,
                'description': description,
                'start': {'dateTime': start_time},
                'end': {'dateTime': end_time},
            }
            
            created_event = service.events().insert(calendarId='primary', body=event).execute()
            return [types.TextContent(type="text", text=json.dumps({"status": "success", "event": created_event}))]
    
    except UnauthenticatedError:
        return [types.TextContent(type="text", text=json.dumps({"error": "auth_required", "auth_url": "http://localhost:3000/auth/login"}))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error executing tool: {e}")]
    
    raise ValueError(f"Tool {name} not found")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
