import asyncio
import os
import json
import sys
from contextlib import AsyncExitStack

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))

from core.mcp_client import MCPClientManager, MCP_SERVERS_FILE

async def test_mcp_manager():
    print("Testing MCPClientManager...")
    
    # Backup existing config if any
    backup_config = None
    if os.path.exists(MCP_SERVERS_FILE):
        with open(MCP_SERVERS_FILE, 'r') as f:
            backup_config = f.read()
    
    # Clear config for test
    if os.path.exists(MCP_SERVERS_FILE):
        os.remove(MCP_SERVERS_FILE)

    async with AsyncExitStack() as stack:
        manager = MCPClientManager(stack)
        
        # Test 1: Load empty
        servers = manager.load_servers()
        assert len(servers) == 0, "Should start empty"
        print("✅ Load empty config")

        # Test 2: Add Server (Mock - we won't actually connect to a real server in this unit test 
        # unless we have a simple echo server. `npx` might be slow or not available in test env.
        # We will try to add a server that fails to connect, but verify config handling logic,
        # OR we can mock connect_server.)
        
        # Let's mock connect_server to avoid needing a real MCP server running for this config test
        async def mock_connect(config):
            print(f"Mock connecting to {config['name']}")
            return True # Just return truthy to simulate success
        
        manager.connect_server = mock_connect
        
        try:
            await manager.add_server("test-server", "echo", ["hello"], {"TEST_ENV": "1"})
        except Exception as e:
            # It might fail if we don't mock it properly on the instance method, 
            # but python allows this monkeypatching.
            pass
            
        # Verify persistence
        with open(MCP_SERVERS_FILE, 'r') as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["name"] == "test-server"
            assert data[0]["env"]["TEST_ENV"] == "1"
        print("✅ Add server & Persistence")

        # Test 3: Remove Server
        await manager.remove_server("test-server")
        
        with open(MCP_SERVERS_FILE, 'r') as f:
            data = json.load(f)
            assert len(data) == 0
        print("✅ Remove server")

    # Restore backup
    if backup_config:
        with open(MCP_SERVERS_FILE, 'w') as f:
            f.write(backup_config)
    elif os.path.exists(MCP_SERVERS_FILE):
        os.remove(MCP_SERVERS_FILE)
        
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    asyncio.run(test_mcp_manager())
