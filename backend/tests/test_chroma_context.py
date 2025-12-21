
import sys
import os
import time

# Add backend to path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.append(backend_dir)

try:
    from core.memory import MemoryStore
except ImportError:
    print("Could not import MemoryStore. Make sure you are running from the backend directory or setup is correct.")
    sys.exit(1)

def test_chroma_retrieval():
    print("Initializing MemoryStore...")
    ms = MemoryStore()
    
    # Clearning collection for clean test (optional, but good for reliable test)
    # ms.client.delete_collection("chat_history") 
    # ms.collection = ms.client.create_collection("chat_history")
    # Actually, let's just add a unique memory
    
    unique_id = str(time.time())
    email_content = f"Subject: Zomato Gold Renewed {unique_id}. Message: Your membership is extended."
    
    print(f"\n1. Adding Memory: {email_content}")
    ms.add_memory("assistant", email_content)
    
    query = "create a file based on above email"
    print(f"\n2. Querying with: '{query}'")
    
    results = ms.query_memory(query, n_results=5)
    
    print(f"\n3. Results found: {len(results)}")
    found = False
    for r in results:
        print(f" - {r}")
        if unique_id in r:
            found = True
            
    if found:
        print("\nSUCCESS: ChromaDB retrieved the email context.")
    else:
        print("\nFAILURE: ChromaDB DID NOT retrieve the email context. Semantic mismatch confirmed.")

if __name__ == "__main__":
    test_chroma_retrieval()
