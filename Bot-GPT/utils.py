import os
from flask import current_app
from models import load_conversation

def get_workspace_path(conversation_id, owner_id):
    """
    Constructs a path to a conversation-specific workspace.
    The path is always based on the conversation's owner.
    """
    if not owner_id or not conversation_id:
        # Try to find the owner if not provided
        from workspace import find_conversation_owner
        owner_id = find_conversation_owner(conversation_id)
        if not owner_id:
            return None

    path = os.path.join(
        current_app.instance_path,
        str(owner_id),
        "workspaces",
        str(conversation_id),
    )
    os.makedirs(path, exist_ok=True)
    return path
