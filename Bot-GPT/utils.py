import os
from flask import current_app
from models import Conversation

def get_workspace_path(conversation_id, user_id):
    """Constructs a path to a conversation-specific workspace."""
    if not user_id or not conversation_id:
        return None

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        owner_id = user_id
    else:
        owner_id = conversation.owner_id

    path = os.path.join(
        current_app.config['USER_DATA_DIR'],
        str(owner_id),
        'workspaces',
        str(conversation_id)
    )
    if not os.path.exists(path):
        os.makedirs(path)
    return path
