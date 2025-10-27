import os
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from utils import get_workspace_path

class MemoryManager:
    """
    Manages the vector memory for conversations, including creating embeddings,
    storing them in a FAISS index, and searching for relevant messages.
    """
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)
        self.dimension = self.model.get_sentence_embedding_dimension()

    def _get_index_path(self, conversation_id, user_id):
        """Constructs the file path for a conversation's FAISS index."""
        workspace = get_workspace_path(conversation_id, user_id)
        if not workspace:
            return None
        return os.path.join(workspace, f"memory_index_{conversation_id}.faiss")

    def _get_or_create_index(self, index_path):
        """Loads a FAISS index from disk or creates a new one if it doesn't exist."""
        if os.path.exists(index_path):
            return faiss.read_index(index_path)
        else:
            # Using IndexFlatL2 for simplicity, good for moderate-sized datasets.
            # L2 distance is a good choice for sentence embeddings.
            return faiss.IndexFlatL2(self.dimension)

    def add_message(self, conversation_id, user_id, message_text):
        """
        Adds a message to the conversation's vector memory.

        Args:
            conversation_id: The ID of the conversation.
            user_id: The ID of the user who owns the conversation.
            message_text: The text content of the message to add.
        """
        index_path = self._get_index_path(conversation_id, user_id)
        if not index_path:
            print("Error: Could not determine index path for memory.")
            return

        index = self._get_or_create_index(index_path)

        # Convert the message to a vector embedding
        embedding = self.model.encode([message_text], convert_to_numpy=True)

        # Add the new vector to the index
        index.add(embedding)

        # Save the updated index back to disk
        faiss.write_index(index, index_path)

    def search_relevant_messages(self, conversation_id, user_id, query, k=5):
        """
        Searches for the most relevant messages in the conversation's memory.

        Args:
            conversation_id: The ID of the conversation.
            user_id: The ID of the user who owns the conversation.
            query: The user's latest query to search for.
            k: The number of relevant messages to retrieve.

        Returns:
            A list of the k most relevant message texts.
        """
        index_path = self._get_index_path(conversation_id, user_id)
        if not index_path or not os.path.exists(index_path):
            return [] # No memory yet, return empty list

        index = faiss.read_index(index_path)

        # Convert the query to a vector embedding
        query_embedding = self.model.encode([query], convert_to_numpy=True)

        # Search the index for the k nearest neighbors
        distances, indices = index.search(query_embedding, k)

        # To retrieve the actual messages, we would need to store them alongside the index.
        # For this implementation, we will assume a separate mechanism to map indices back to messages.
        # As a placeholder, this function will need to be updated to return the actual text.
        # For now, we can simulate this by returning a list of placeholders.

        # NOTE: This part is a placeholder. A complete implementation would require
        # storing the original messages and mapping the returned `indices` back to them.
        # For example, in a file or a simple database keyed by the index.

        # We need to retrieve the actual messages. Let's assume we have a way to do that.
        # For the purpose of this implementation, we will need to store the messages
        # in a file or a database. Let's create a simple text file for that.

        message_store_path = os.path.join(get_workspace_path(conversation_id, user_id), f"message_store_{conversation_id}.txt")
        if not os.path.exists(message_store_path):
            return []

        with open(message_store_path, 'r') as f:
            all_messages = f.readlines()

        relevant_messages = [all_messages[i].strip() for i in indices[0] if i < len(all_messages)]

        return relevant_messages

    def add_message_and_get_store(self, conversation_id, user_id, message_text):
        """
        A helper function to add a message to both the FAISS index and a simple text file store.
        This is a simplified approach for demonstration. A more robust system
        would use a database.
        """
        index_path = self._get_index_path(conversation_id, user_id)
        workspace_path = get_workspace_path(conversation_id, user_id)
        if not index_path or not workspace_path:
            print("Error: Could not determine paths for memory.")
            return

        # Add to FAISS index
        index = self._get_or_create_index(index_path)
        embedding = self.model.encode([message_text], convert_to_numpy=True)
        index.add(embedding)
        faiss.write_index(index, index_path)

        # Add to simple text file store
        message_store_path = os.path.join(workspace_path, f"message_store_{conversation_id}.txt")
        with open(message_store_path, 'a') as f:
            f.write(message_text + '\n')
