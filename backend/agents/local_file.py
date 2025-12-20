
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import json
import os
import glob
import subprocess
import fnmatch
import pypdf
from pathlib import Path

# Initialize MCP Server
app = Server("local-file-mcp-server")

# Default search path - inferring relevant windows path from WSL
# This is a heuristic. Ideally strict configuration or user input is better, 
# but for this agent we try to be helpful.
DEFAULT_SEARCH_PATH = "/mnt/c/Users/Naveen Raj" 
if not os.path.exists(DEFAULT_SEARCH_PATH):
    # Fallback to current directory or standard C drive
    DEFAULT_SEARCH_PATH = "/mnt/c/Users"

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_local_files",
            description="Search for local files on the user's computer. Supports filtering by extension (e.g. *.pdf, *.exe) or name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Filename pattern to search for (glob format, e.g. '*.pdf', '*game*').",
                    },
                    "directory": {
                        "type": "string",
                        "description": f"Directory to search in. Defaults to {DEFAULT_SEARCH_PATH}."
                    },
                     "limit": {
                        "type": "integer",
                        "description": "Max files to return (default 5).",
                        "default": 5
                    }
                }
            }
        ),
        types.Tool(
            name="read_local_file",
            description="Read the text content of a local file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file."
                    }
                },
                "required": ["file_path"]
            }
        ),
        types.Tool(
            name="open_file",
            description="Open a file in its default application (e.g. PDF in Acrobat, Browser for HTML). THIS IS DIFFERENT FROM READ. Use this when the user wants to see the file in a separate window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file."
                    }
                },
                "required": ["file_path"]
            }
        ),
        types.Tool(
            name="locate_file",
            description="Open a file location in simple file manager (Windows Explorer).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file."
                    }
                },
                "required": ["file_path"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    try:
        if name == "list_local_files":
            query = arguments.get("query", "*")
            directory = arguments.get("directory", DEFAULT_SEARCH_PATH)
            limit = arguments.get("limit", 5)
            
            # Resolve relative paths / common aliases with WSL awareness
            is_wsl = False
            try:
                with open('/proc/version', 'r') as f:
                    if 'microsoft' in f.read().lower():
                        is_wsl = True
            except:
                pass

            home_dir = os.path.expanduser("~")
            
            # Common folders to check
            common_folders = ['downloads', 'documents', 'desktop', 'pictures', 'videos', 'music']
            
            target_directory = directory
            
            if directory.lower() in common_folders:
                folder_name = directory.capitalize()
                
                # 1. Check WSL/Linux Native Path first (e.g. /home/user/Documents)
                wsl_path = os.path.join(home_dir, folder_name)
                
                # 2. Check Windows Path (e.g. /mnt/c/Users/Name/Documents)
                win_path = None
                if is_wsl:
                    # Try to detect Windows username from /mnt/c/Users
                    # Heuristic: Find first non-public, non-default user in /mnt/c/Users
                    try:
                        c_users = "/mnt/c/Users"
                        if os.path.exists(c_users):
                            for u in os.listdir(c_users):
                                if u.lower() not in ['public', 'default', 'default user', 'desktop.ini', 'all users']:
                                    potential_win_path = os.path.join(c_users, u, folder_name)
                                    if os.path.exists(potential_win_path):
                                        win_path = potential_win_path
                                        break
                    except:
                        pass
                
                # Decision Logic: User asked: "if the folder exist in wsl itslef then take it from wsl"
                if os.path.exists(wsl_path):
                    target_directory = wsl_path
                elif win_path and os.path.exists(win_path):
                    target_directory = win_path
                else:
                    # Fallback to default search path logic if specific folder not found
                    target_directory = os.path.join(DEFAULT_SEARCH_PATH, folder_name)
            
            elif not os.path.exists(directory) and not directory.startswith("/"):
                 # Try joining with default path if it's just a folder name
                 possible_path = os.path.join(DEFAULT_SEARCH_PATH, directory)
                 if os.path.exists(possible_path):
                     target_directory = possible_path

            directory = target_directory

            # Ensure path exists
            if not os.path.exists(directory):
                return [types.TextContent(type="text", text=f"Error: Directory {directory} does not exist. Please specify full path or use common folders like 'Downloads', 'Documents'.")]

            files = []
            if "*" not in query and "?" not in query:
                search_pattern = f"*{query}*"
            else:
                search_pattern = query
            
            # Optimization: Use os.walk with pruning instead of rglob
            # This avoids traversing massive directories like AppData or node_modules
            EXCLUDE_DIRS = {'AppData', 'node_modules', '__pycache__', 'Windows', 'Program Files', 'Program Files (x86)', 
                            '.git', '.vscode', 'Library', 'CrossDevice', 'Intel', 'Application Data'}
            
            collected_files = []
            SAFETY_LIMIT = 1000 # Don't scan forever
            
            for root, dirs, filenames in os.walk(directory):
                # Prune directories in-place
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
                
                for filename in filenames:
                    if fnmatch.fnmatch(filename, search_pattern):
                        full_path = os.path.join(root, filename)
                        try:
                            stat = os.stat(full_path)
                            size = stat.st_size
                            mtime = stat.st_mtime
                        except OSError:
                            size = 0
                            mtime = 0
                            
                        collected_files.append({
                            "name": filename,
                            "path": full_path,
                            "size": size,
                            "mtime": mtime
                        })
                        
                        if len(collected_files) >= SAFETY_LIMIT:
                            break
                            
                if len(collected_files) >= SAFETY_LIMIT:
                    break
            
            # Sort by modification time descending (newest first)
            collected_files.sort(key=lambda x: x['mtime'], reverse=True)
            
            # Apply limit
            final_files = collected_files[:limit]
            
            # Remove mtime from output to keep it clean (optional, keeping it doesn't hurt)
            results = [{k: v for k, v in f.items() if k != 'mtime'} for f in final_files]
            
            return [types.TextContent(type="text", text=json.dumps({"files": results}))]

        elif name == "read_local_file":
            file_path = arguments.get("file_path")
            if not file_path:
                 raise ValueError("file_path is required")
            
            if not os.path.exists(file_path):
                 return [types.TextContent(type="text", text="Error: File not found.")]
            
            # Check for PDF
            if file_path.lower().endswith('.pdf'):
                try:
                    reader = pypdf.PdfReader(file_path)
                    text = ""
                    # Extract text from first 5 pages max to save tokens
                    for i in range(min(5, len(reader.pages))):
                        text += reader.pages[i].extract_text() + "\n"
                    
                    if not text.strip():
                        text = "[PDF contains no extractable text (scanned image?)]"
                    else:
                        text = f"[Content of {file_path} (First 5 pages)]\n" + text
                    
                    return [types.TextContent(type="text", text=json.dumps({
                        "path": file_path,
                        "content": text
                    }))]
                except Exception as e:
                     return [types.TextContent(type="text", text=f"Error reading PDF: {e}")]

            # Check for other Binary Files (Simple Ext Check)
            BINARY_EXTS = {'.exe', '.dll', '.zip', '.tar', '.gz', '.iso', '.img', '.bin', '.mp4', '.mp3', '.png', '.jpg', '.jpeg'}
            _, ext = os.path.splitext(file_path)
            if ext.lower() in BINARY_EXTS:
                 return [types.TextContent(type="text", text="Error: Cannot read binary file. Please use 'locate_file' instead.")]

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(4000) # Increased limit for text files
                    if len(content) == 4000:
                        content += "\n... (truncated)"
                
                return [types.TextContent(type="text", text=json.dumps({
                    "path": file_path,
                    "content": content
                }))]
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error reading file: {e}")]

        elif name == "open_file":
            file_path = arguments.get("file_path")
            if not file_path:
                 raise ValueError("file_path is required")
            
            # Convert WSL path to Windows path
            try:
                # wslpath -w <linux_path>
                result = subprocess.run(["wslpath", "-w", file_path], capture_output=True, text=True, check=True)
                win_path = result.stdout.strip()
                
                # Open file with default app
                # cmd.exe /c start "" "path"
                subprocess.run(["cmd.exe", "/c", "start", "", win_path])
                return [types.TextContent(type="text", text=f"Opened {win_path} in default application.")]
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error opening file: {e}")]

        elif name == "locate_file":
            file_path = arguments.get("file_path")
            if not file_path:
                 raise ValueError("file_path is required")
            
            # Convert WSL path to Windows path
            try:
                # wslpath -w <linux_path>
                result = subprocess.run(["wslpath", "-w", file_path], capture_output=True, text=True, check=True)
                win_path = result.stdout.strip()
                
                # Open explorer with /select
                # Explorer might be in simple /mnt/c/Windows/explorer.exe
                # Or just 'explorer.exe' if in path
                subprocess.run(["explorer.exe", f"/select,{win_path}"])
                return [types.TextContent(type="text", text=f"Opened {win_path} in Explorer.")]
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error locating file: {e}")]

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
