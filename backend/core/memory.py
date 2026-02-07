import chromadb
from typing import Callable, Optional
import uuid
import os
import json

class MemoryStore:
    def __init__(
        self,
        storage_path="chroma_db",
        model="llama3",
        embed_fn: Optional[Callable[[str], list[float] | None]] = None,
    ):
        # Initialize ChromaDB
        # We use a persistent client so data survives restarts
        self.storage_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma_db")
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)
            
        self.client = chromadb.PersistentClient(path=self.storage_path)
        self.collection = self.client.get_or_create_collection(name="chat_history")
        self.model = model
        self._embed_fn = embed_fn
        print(f"DEBUG: MemoryStore initialized at {self.storage_path} with model {self.model}")

    def get_embedding(self, text):
        if self._embed_fn:
            try:
                return self._embed_fn(text)
            except Exception as e:
                print(f"Error getting embedding from configured provider: {e}")
                return None
        try:
            # Default: Use Ollama for embeddings (best-effort)
            import ollama

            response = ollama.embeddings(model=self.model, prompt=text)
            return response["embedding"]
        except Exception as e:
            print(f"Error getting embedding from Ollama: {e}")
            return None

    def add_memory(self, role, content):
        if not content or not content.strip():
            return
            
        embedding = self.get_embedding(content)
        if not embedding:
            return

        doc_id = str(uuid.uuid4())
        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"role": role, "timestamp": str(os.path.getmtime(__file__))}] # Dummy timestamp for now
        )
        print(f"DEBUG: Added memory to DB: {role}: {content[:30]}...")

    def query_memory(self, query, n_results=5):
        embedding = self.get_embedding(query)
        if not embedding:
            return []

        try:
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results
            )
            
            # Format results
            memories = []
            if results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    role = results['metadatas'][0][i].get('role', 'unknown')
                    memories.append(f"{role}: {doc}")
            
            return memories
        except Exception as e:
            print(f"Error querying memory: {e}")
            return []

    def clear_memory(self):
        try:
            # Delete all items instead of dropping collection to keep UUID stable
            # fetch all ids first
            result = self.collection.get()
            if result and 'ids' in result and result['ids']:
                self.collection.delete(ids=result['ids'])
                
            print("DEBUG: Memory Store cleared (items deleted).")
            return True
        except Exception as e:
            print(f"Error clearing memory: {e}")
            # Fallback: try to recreate
            try:
                self.client.delete_collection("chat_history")
                self.collection = self.client.create_collection(name="chat_history")
                return True
            except:
                return False
