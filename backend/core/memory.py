import chromadb
from typing import Any, Callable, Optional
import uuid
import os
import json
from datetime import datetime

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
        # CRITICAL: AWS Bedrock embedding models have TWO limits:
        # 1. Character limit: 50,000 chars
        # 2. Token limit: 8,192 tokens (this is the real constraint!)
        # 
        # Ratio: ~3 chars per token
        # To stay under 8,192 tokens, limit to ~20,000 chars (~6,600 tokens with safety margin)
        MAX_CHARS = 20000
        if len(text) > MAX_CHARS:
            original_len = len(text)
            text = text[:MAX_CHARS]
            print(f"WARNING: Truncated embedding text from {original_len} to {MAX_CHARS} chars to stay within token limit")
        
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

    def add_memory(self, role, content, metadata: dict[str, Any] | None = None):
        if not content or not content.strip():
            return
            
        embedding = self.get_embedding(content)
        if not embedding:
            return

        doc_id = str(uuid.uuid4())
        base_meta: dict[str, Any] = {
            "role": role,
            "timestamp": str(os.path.getmtime(__file__)),  # Dummy timestamp for now
        }
        if metadata and isinstance(metadata, dict):
            base_meta.update(metadata)

        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[base_meta]
        )
        print(f"DEBUG: Added memory to DB: {role}: {content[:30]}...")

    def query_memory(self, query, n_results=5, where: dict[str, Any] | None = None):
        embedding = self.get_embedding(query)
        if not embedding:
            return []

        try:
            query_kwargs: dict[str, Any] = {
                "query_embeddings": [embedding],
                "n_results": n_results,
            }
            if where and isinstance(where, dict):
                query_kwargs["where"] = where

            results = self.collection.query(**query_kwargs)
            
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

    def add_tool_execution(self, session_id: str, tool_name: str, 
                           tool_args: dict, tool_output: str, 
                           timestamp: str = None, agent_id: str = None):
        """Store tool execution details for session-scoped retrieval.
        
        ID-AGNOSTIC: Automatically extracts any field ending with '_id' or 'Id'
        from the tool output for easy retrieval.
        """
        # Create searchable text representation
        content = f"Tool: {tool_name}\nArguments: {json.dumps(tool_args)}\nOutput: {tool_output}"
        
        # Store with rich metadata
        metadata = {
            "type": "tool_execution",
            "session_id": session_id,
            "tool_name": tool_name,
            "timestamp": timestamp or datetime.now().isoformat()
        }
        if agent_id:
            metadata["agent_id"] = agent_id
        
        # Add parsed IDs as metadata for easy retrieval (ID-AGNOSTIC)
        try:
            parsed_output = json.loads(tool_output)
            if isinstance(parsed_output, dict):
                # Automatically extract ANY field ending with "_id" or "Id"
                for key, value in parsed_output.items():
                    if (key.endswith("_id") or key.endswith("Id") or key.lower() in ["id", "uuid"]) and value is not None:
                        metadata[key] = str(value)
                
                # Also check nested dicts for IDs (one level deep)
                for key, value in parsed_output.items():
                    if isinstance(value, dict):
                        for nested_key, nested_value in value.items():
                            if (nested_key.endswith("_id") or nested_key.endswith("Id")) and nested_value is not None:
                                metadata[f"{key}.{nested_key}"] = str(nested_value)
        except:
            pass
        
        self.add_memory("tool", content, metadata)

    def get_session_tool_outputs(self, session_id: str, tool_name: str = None, 
                                 n_results: int = 10, agent_id: str = None):
        """Retrieve recent tool outputs for the current session.
        
        Returns tool execution records with extracted IDs available in metadata.
        Optionally filtered by agent_id for agent-scoped isolation.
        """
        # Build filter conditions — ChromaDB requires $and for 3+ conditions
        conditions = [
            {"session_id": session_id},
            {"type": "tool_execution"},
        ]
        if tool_name:
            conditions.append({"tool_name": tool_name})
        if agent_id:
            conditions.append({"agent_id": agent_id})
        
        # ChromaDB: 1 condition = flat dict, 2+ conditions = $and
        if len(conditions) == 1:
            where_filter = conditions[0]
        else:
            where_filter = {"$and": conditions}
        
        try:
            # Query by metadata filter
            results = self.collection.get(
                where=where_filter,
                limit=n_results
            )
            return results
        except Exception as e:
            print(f"Error retrieving session tool outputs: {e}")
            return None

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
    
    # ========================================================================
    # DYNAMIC SESSION-SCOPED RAG
    # Embeddings created on-demand for vague queries, auto-cleaned after session
    # ========================================================================
    
    def embed_report_for_session(
        self,
        session_id: str,
        report_data: list[dict],
        report_type: str,
        chunk_size: int = 50
    ) -> dict:
        """
        Create temporary embeddings for a report, scoped to current session.
        
        Used for exploratory/vague queries where semantic search is beneficial.
        Embeddings are automatically cleaned up when session ends.
        
        Args:
            session_id: Current session ID
            report_data: List of records from the report
            report_type: Type of report (orders, payments, etc.)
            chunk_size: Rows per chunk
        
        Returns:
            {
              "collection_name": str,
              "chunks_embedded": int,
              "total_rows": int
            }
        """
        if not report_data:
            return {"error": "No report data provided"}
        
        # Create unique collection name for this session + report
        collection_name = f"session_{session_id}_{report_type}_{datetime.now().timestamp()}"
        
        try:
            # Create ephemeral collection
            session_collection = self.client.get_or_create_collection(collection_name)
            
            # Chunk the report data
            chunks = []
            for i in range(0, len(report_data), chunk_size):
                chunks.append(report_data[i:i + chunk_size])
            
            print(f"DEBUG: Embedding {len(chunks)} chunks for session {session_id}")
            
            # Embed each chunk
            embedded_count = 0
            for i, chunk in enumerate(chunks):
                # Create semantic summary for better search
                chunk_text = self._create_semantic_chunk_summary(
                    chunk, 
                    report_type,
                    chunk_index=i,
                    total_chunks=len(chunks)
                )
                
                # Pre-truncate chunks to stay within token limits
                # get_embedding will do final truncation to 20,000 chars (~6,600 tokens)
                # But we pre-truncate here to 12,000 chars (~4,000 tokens) for better chunk quality
                MAX_CHUNK_CHARS = 12000
                if len(chunk_text) > MAX_CHUNK_CHARS:
                    chunk_text = chunk_text[:MAX_CHUNK_CHARS] + "\n... (chunk truncated)"
                    print(f"DEBUG: Pre-truncated chunk {i} summary to {MAX_CHUNK_CHARS} chars")
                
                # Generate embedding
                embedding = self.get_embedding(chunk_text)
                if not embedding:
                    print(f"WARNING: Failed to embed chunk {i}")
                    continue
                
                # Store chunk with metadata
                session_collection.add(
                    ids=[f"chunk_{i}"],
                    embeddings=[embedding],
                    documents=[json.dumps(chunk)],  # Store actual data
                    metadatas=[{
                        "chunk_index": i,
                        "row_count": len(chunk),
                        "report_type": report_type,
                        "session_id": session_id,
                        "timestamp": datetime.now().isoformat()
                    }]
                )
                embedded_count += 1
            
            print(f"DEBUG: Successfully embedded {embedded_count}/{len(chunks)} chunks")
            
            return {
                "collection_name": collection_name,
                "chunks_embedded": embedded_count,
                "total_rows": len(report_data),
                "chunk_size": chunk_size
            }
            
        except Exception as e:
            print(f"Error embedding report for session: {e}")
            return {"error": str(e)}
    
    def search_session_embeddings(
        self,
        session_id: str,
        query: str,
        n_results: int = 3,
        collection_name: str = None
    ) -> list[dict]:
        """
        Semantically search session-scoped report embeddings.
        
        Args:
            session_id: Current session ID
            query: Natural language search query (e.g., "concerning patterns")
            n_results: Max chunks to return
            collection_name: Specific collection to search (optional)
        
        Returns:
            List of matching chunks with similarity scores
        """
        try:
            # Find all session collections if specific name not provided
            if collection_name:
                collection_names = [collection_name]
            else:
                # List all collections and filter by session
                all_collections = self.client.list_collections()
                collection_names = [
                    c.name for c in all_collections 
                    if c.name.startswith(f"session_{session_id}_")
                ]
            
            if not collection_names:
                print(f"DEBUG: No session embeddings found for {session_id}")
                return []
            
            # Embed the query
            query_embedding = self.get_embedding(query)
            if not query_embedding:
                return []
            
            all_results = []
            
            # Search each session collection
            for coll_name in collection_names:
                collection = self.client.get_collection(coll_name)
                
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results
                )
                
                if results and results.get('documents') and results['documents'][0]:
                    for i, doc in enumerate(results['documents'][0]):
                        all_results.append({
                            "chunk_data": json.loads(doc),
                            "similarity_score": 1 - results['distances'][0][i],
                            "metadata": results['metadatas'][0][i],
                            "collection": coll_name
                        })
            
            # Sort by similarity score (highest first)
            all_results.sort(key=lambda x: x['similarity_score'], reverse=True)
            
            # Return top N results
            return all_results[:n_results]
            
        except Exception as e:
            print(f"Error searching session embeddings: {e}")
            return []
    
    def clear_session_embeddings(self, session_id: str) -> int:
        """
        Delete all session-scoped embeddings for cleanup.
        
        Called when session ends or user explicitly clears context.
        
        Returns:
            Number of collections deleted
        """
        try:
            # Find all session collections
            all_collections = self.client.list_collections()
            session_prefix = f"session_{session_id}_"
            
            deleted_count = 0
            for collection in all_collections:
                if collection.name.startswith(session_prefix):
                    try:
                        self.client.delete_collection(collection.name)
                        deleted_count += 1
                        print(f"DEBUG: Deleted session collection {collection.name}")
                    except Exception as e:
                        print(f"Error deleting collection {collection.name}: {e}")
            
            if deleted_count > 0:
                print(f"DEBUG: Cleared {deleted_count} session embedding collections")
            
            return deleted_count
            
        except Exception as e:
            print(f"Error clearing session embeddings: {e}")
            return 0
    
    def _create_semantic_chunk_summary(
        self,
        chunk: list[dict],
        report_type: str,
        chunk_index: int = 0,
        total_chunks: int = 1
    ) -> str:
        """
        Create rich semantic text representation of a chunk for embedding.
        
        This is critical - the better the summary, the better semantic search works.
        """
        if not chunk:
            return ""
        
        # Import pandas for analysis (already available in the codebase)
        try:
            import pandas as pd
        except ImportError:
            # Fallback to simple text representation
            return self._simple_chunk_summary(chunk, report_type)
        
        df = pd.DataFrame(chunk)
        
        summary_parts = [
            f"Report Type: {report_type}",
            f"Chunk {chunk_index + 1} of {total_chunks}",
            f"Contains {len(chunk)} records"
        ]
        
        # Analyze each column
        for col in df.columns:
            try:
                if pd.api.types.is_numeric_dtype(df[col]):
                    # Numeric column - provide statistics
                    summary_parts.append(
                        f"{col}: ranges from {df[col].min()} to {df[col].max()}, "
                        f"average {df[col].mean():.2f}, total {df[col].sum():.2f}"
                    )
                elif pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
                    # Categorical column - provide top values
                    top_values = df[col].value_counts().head(3)
                    if not top_values.empty:
                        summary_parts.append(
                            f"{col}: {', '.join(str(v) for v in top_values.index[:3])}"
                        )
            except Exception as e:
                # Skip problematic columns
                continue
        
        # Add sample records for context
        summary_parts.append("\nSample Records:")
        for i, row in enumerate(chunk[:3], 1):
            record_text = ", ".join(
                f"{k}={v}" for k, v in row.items() 
                if v is not None and str(v).strip()
            )
            summary_parts.append(f"{i}. {record_text[:200]}")
        
        return "\n".join(summary_parts)
    
    def _simple_chunk_summary(self, chunk: list[dict], report_type: str) -> str:
        """Fallback summary method when pandas not available."""
        summary = f"Report: {report_type}, {len(chunk)} records\n"
        for i, record in enumerate(chunk[:3], 1):
            record_text = ", ".join(f"{k}={v}" for k, v in record.items() if v)
            summary += f"{i}. {record_text[:200]}\n"
        return summary

