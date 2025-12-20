from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import json
from services.google import get_drive_service, UnauthenticatedError

from googleapiclient.http import MediaIoBaseUpload
import io

# Initialize MCP Server
app = Server("drive-mcp-server")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_files",
            description="List recent files from Google Drive. Returns ID, name, and webViewLink.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of files to return (default 5)",
                        "default": 5
                    },
                    "query": {
                        "type": "string",
                        "description": "Drive search query (e.g. \"name contains 'budget'\", \"mimeType = 'application/pdf'\")",
                    }
                }
            }
        ),
        types.Tool(
            name="create_file",
            description="Create a new file or folder in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the file/folder"},
                    "mimeType": {"type": "string", "description": "MIME type (e.g. 'application/vnd.google-apps.folder', 'application/vnd.google-apps.document', 'text/plain')"},
                    "content": {"type": "string", "description": "Text content for the file (optional)"}
                },
                "required": ["name", "mimeType"]
            }
        ),
        types.Tool(
            name="read_file_content",
            description="Read the text content of a file (Google Doc, Sheet, or text file).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "The ID of the file to read"}
                },
                "required": ["file_id"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    try:
        service = get_drive_service()

        if name == "list_files":
            limit = arguments.get("limit", 5)
            query = arguments.get("query")
            
            results = service.files().list(
                pageSize=limit, 
                q=query,
                fields="nextPageToken, files(id, name, webViewLink, iconLink, thumbnailLink, mimeType)"
            ).execute()
            files = results.get('files', [])
            
            return [types.TextContent(type="text", text=json.dumps({"files": files}))]

        elif name == "create_file":
            name = arguments.get("name")
            mimeType = arguments.get("mimeType")
            content = arguments.get("content")
            
            file_metadata = {'name': name, 'mimeType': mimeType}
            media = None
            
            if content:
                # If creating a Google Doc, we upload text/plain and let Drive convert it
                if mimeType == 'application/vnd.google-apps.document':
                     file_metadata['mimeType'] = 'application/vnd.google-apps.document'
                     upload_mime = 'text/plain'
                else:
                     upload_mime = mimeType
                
                fh = io.BytesIO(content.encode('utf-8'))
                media = MediaIoBaseUpload(fh, mimetype=upload_mime)

            file = service.files().create(body=file_metadata, media_body=media, fields='id, name, webViewLink').execute()
            return [types.TextContent(type="text", text=json.dumps({"status": "success", "file": file}))]

        elif name == "read_file_content":
            file_id = arguments.get("file_id")
            
            # Get metadata first to check mimeType
            file_meta = service.files().get(fileId=file_id).execute()
            mime_type = file_meta.get('mimeType')
            
            content = ""
            if mime_type == 'application/vnd.google-apps.document':
                # Export Google Doc as text
                content = service.files().export(fileId=file_id, mimeType='text/plain').execute().decode('utf-8')
            elif mime_type == 'application/vnd.google-apps.spreadsheet':
                # Export Sheet as CSV (first sheet usually)
                content = service.files().export(fileId=file_id, mimeType='text/csv').execute().decode('utf-8')
            elif mime_type.startswith('text/'):
                # Download plain text
                content = service.files().get(fileId=file_id, alt='media').execute().decode('utf-8')
            else:
                return [types.TextContent(type="text", text=f"Error: Unsupported file type for reading: {mime_type}")]
            
            return [types.TextContent(type="text", text=json.dumps({"file_id": file_id, "name": file_meta.get('name'), "content": content}))]
    
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
