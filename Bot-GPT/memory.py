import os
import json
import time
from filelock import FileLock
from flask import current_app

class MemoryManager:
    """
    Manages persistent memory for the AI agent.
    Scopes:
    - user: Memory specific to a user (across all their projects).
    - project: Memory specific to a project/workspace (shared by all users in that project).
    """

    def __init__(self, user_id=None, project_id=None):
        self.user_id = user_id
        self.project_id = project_id
        self.user_memory_file = None
        self.project_memory_file = None

        if current_app:
            if user_id:
                self.user_memory_file = os.path.join(current_app.config["USER_DATA_DIR"], "user_memory.json")
            if project_id:
                # Assuming project_id maps to conversation_id for now, or a workspace ID.
                # In this app, workspace is by owner_id/conversation_id.
                # Let's verify how project_id is passed. If it's conversation_id, we need owner_id to find path.
                # For simplicity, let's assume project_id IS the absolute path to the workspace memory file
                # OR we handle path construction outside.
                # Actually, let's look at how get_workspace_path works.
                pass

    def _get_file_path(self, scope):
        if scope == "user":
            return self.user_memory_file
        elif scope == "project":
            return self.project_memory_file
        return None

    def _load_memory(self, path):
        if not path:
            return {}
        lock = FileLock(f"{path}.lock")
        with lock:
            if not os.path.exists(path):
                return {}
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {}

    def _save_memory(self, path, data):
        if not path:
            return
        lock = FileLock(f"{path}.lock")
        with lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

    def set_project_memory_file(self, owner_id, conversation_id):
        """Sets the path for project-specific memory."""
        if current_app and owner_id and conversation_id:
             self.project_memory_file = os.path.join(
                current_app.instance_path,
                str(owner_id),
                "workspaces",
                str(conversation_id),
                ".agent",
                "memory.json"
            )

    def remember(self, scope, key, value):
        """Saves a fact to memory."""
        path = self._get_file_path(scope)
        if not path:
             return f"Error: No memory file configured for scope '{scope}'."
        
        memory = self._load_memory(path)
        
        # User memory is keyed by user_id
        if scope == "user":
            if str(self.user_id) not in memory:
                memory[str(self.user_id)] = {}
            memory[str(self.user_id)][key] = {
                "value": value,
                "timestamp": time.time()
            }
        else:
            # Project memory is flat for the project
            memory[key] = {
                "value": value,
                "timestamp": time.time()
            }

        self._save_memory(path, memory)
        return f"Successfully remembered ({scope}): {key} = {value}"

    def recall(self, scope, key):
        """Retrieves a specific fact."""
        path = self._get_file_path(scope)
        if not path:
            return None
            
        memory = self._load_memory(path)
        
        if scope == "user":
            user_mem = memory.get(str(self.user_id), {})
            item = user_mem.get(key)
        else:
            item = memory.get(key)
            
        return item.get("value") if item else None

    def get_all_context(self):
        """Retrieves all relevant context for the current user and project."""
        context = []
        
        # User Memory
        if self.user_memory_file:
            u_mem = self._load_memory(self.user_memory_file).get(str(self.user_id), {})
            if u_mem:
                context.append("--- USER MEMORY ---")
                for k, v in u_mem.items():
                    context.append(f"{k}: {v['value']}")
        
        # Project Memory
        if self.project_memory_file:
            p_mem = self._load_memory(self.project_memory_file)
            if p_mem:
                context.append("--- PROJECT MEMORY ---")
                for k, v in p_mem.items():
                    context.append(f"{k}: {v['value']}")
                    
        return "\n".join(context)

    def forget(self, scope, key):
        """Deletes a fact."""
        path = self._get_file_path(scope)
        if not path:
            return "Error: Invalid scope."
            
        memory = self._load_memory(path)
        
        if scope == "user":
            if str(self.user_id) in memory and key in memory[str(self.user_id)]:
                del memory[str(self.user_id)][key]
                self._save_memory(path, memory)
                return f"Forgot ({scope}): {key}"
        else:
            if key in memory:
                del memory[key]
                self._save_memory(path, memory)
                return f"Forgot ({scope}): {key}"
                
        return f"Key '{key}' not found in {scope} memory."
