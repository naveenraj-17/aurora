import sys
import os

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.memory import MemoryStore

def test_clear():
    print("Initializing MemoryStore...")
    ms = MemoryStore()
    
    print("Adding dummy memory...")
    ms.add_memory("user", "This is a test memory that should be deleted.")
    
    print("Querying memory (expecting result)...")
    res = ms.query_memory("test memory")
    print(f"Result: {res}")
    
    if not res:
        print("ERROR: Failed to add memory.")
        return

    print("Clearing memory...")
    ms.clear_memory()
    
    print("Querying memory (expecting empty)...")
    res_after = ms.query_memory("test memory")
    print(f"Result after clear: {res_after}")
    
    if not res_after:
        print("SUCCESS: Memory collection is empty.")
    else:
        print("FAILURE: Memory still exists.")

if __name__ == "__main__":
    test_clear()
