import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

async def test_mcp_server():
    print("Starting MCP connection test...")
    
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "chrome-devtools-mcp@latest"],
        env=os.environ.copy()
    )

    async with AsyncExitStack() as stack:
        try:
            print("Connecting via stdio...")
            read, write = await stack.enter_async_context(stdio_client(server_params))
            
            print("Initializing session...")
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            
            print("Listing tools...")
            tools = await session.list_tools()
            
            print(f"Found {len(tools.tools)} tools:")
            for tool in tools.tools:
                print(f" - {tool.name}")
                
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_server())
