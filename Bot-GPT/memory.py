import os
import time
from flask import current_app

try:
    import chromadb
except ImportError:
    chromadb = None

class MemoryManager:
    """
    Manages persistent memory for the AI agent using ChromaDB for vectorized recall.
    Scopes:
    - user: Memory specific to a user (across all their projects).
    - project: Memory specific to a project/workspace (shared by all users in that project).
    """

    def __init__(self, user_id=None, project_id=None):
        self.user_id = user_id
        self.project_id = project_id
        self.chroma_client = None
        self.user_collection = None
        self.project_collection = None
        
        if current_app and chromadb:
            persist_directory = os.path.join(current_app.instance_path, "user_data", "chroma")
            os.makedirs(persist_directory, exist_ok=True)
            self.chroma_client = chromadb.PersistentClient(path=persist_directory)
            
            # Initialize Collections
            if user_id:
                self.user_collection = self.chroma_client.get_or_create_collection(
                    name=f"user_memory_{user_id}"
                )
            
            # project_id is conversation_id here
            if project_id:
                self.project_collection = self.chroma_client.get_or_create_collection(
                    name=f"project_memory_{project_id}"
                )

    def set_project_memory_file(self, owner_id, conversation_id):
        """Sets the project memory collection based on conversation ID."""
        if self.chroma_client and conversation_id:
            self.project_collection = self.chroma_client.get_or_create_collection(
                name=f"project_memory_{conversation_id}"
            )

    def remember(self, scope, key, value):
        """Saves a fact to vectorized memory."""
        collection = self.user_collection if scope == "user" else self.project_collection
        if not collection:
            return f"Error: No collection available for scope '{scope}'."

        # Use the key as the ID for easy exact lookups/overwrites
        # The value is the document for semantic search
        timestamp = time.time()
        collection.upsert(
            ids=[key],
            documents=[value],
            metadatas=[{"key": key, "timestamp": timestamp, "scope": scope}]
        )
        return f"Successfully remembered ({scope}): {key} = {value}"

    def recall(self, scope, key):
        """Retrieves a specific fact by key."""
        collection = self.user_collection if scope == "user" else self.project_collection
        if not collection:
            return None
            
        result = collection.get(ids=[key])
        if result and result["documents"]:
            return result["documents"][0]
        return None

    def query_memory(self, query, scope="user", n_results=3):
        """Perform semantic search over memory."""
        collection = self.user_collection if scope == "user" else self.project_collection
        if not collection:
            return []
            
        results = collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        items = []
        if results and results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                items.append({
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i]
                })
        return items

    def get_all_context(self, query=None):
        """
        Retrieves relevant context. If query is provided, performs semantic search.
        Otherwise, returns recent facts.
        """
        context_parts = []
        
        # User Memory (Semantic first, then recent if no query)
        if self.user_collection:
            u_mem_parts = []
            if query:
                results = self.query_memory(query, scope="user")
                for item in results:
                    u_mem_parts.append(f"- {item['metadata']['key']}: {item['content']}")
            else:
                # Just get some recent ones
                results = self.user_collection.get(limit=10)
                if results and results["documents"]:
                    for i in range(len(results["documents"])):
                        u_mem_parts.append(f"- {results['metadatas'][i]['key']}: {results['documents'][i]}")
            
            if u_mem_parts:
                context_parts.append("--- USER MEMORY ---")
                context_parts.extend(u_mem_parts)

        # Project Memory
        if self.project_collection:
            p_mem_parts = []
            if query:
                results = self.query_memory(query, scope="project")
                for item in results:
                    p_mem_parts.append(f"- {item['metadata']['key']}: {item['content']}")
            else:
                results = self.project_collection.get(limit=10)
                if results and results["documents"]:
                    for i in range(len(results["documents"])):
                        p_mem_parts.append(f"- {results['metadatas'][i]['key']}: {results['documents'][i]}")
            
            if p_mem_parts:
                context_parts.append("--- PROJECT MEMORY ---")
                context_parts.extend(p_mem_parts)
                    
        return "\n".join(context_parts)

    def forget(self, scope, key):
        """Deletes a fact by key."""
        collection = self.user_collection if scope == "user" else self.project_collection
        if not collection:
            return "Error: Invalid scope."
            
        collection.delete(ids=[key])
        return f"Forgot ({scope}): {key}"
