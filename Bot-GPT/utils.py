import os
from flask import current_app
from flask_login import login_required
from extensions import socketio
from models import Conversation

PLAN_APPROVALS = {}


@socketio.on("user_response")
@login_required
def handle_user_response(data):
    """Handles user's response to a plan."""
    conversation_id = data.get("conversation_id")
    if conversation_id in PLAN_APPROVALS:
        PLAN_APPROVALS[conversation_id] = data.get("response")
        if data.get("response") == "reject":
            socketio.emit(
                "ai_response",
                {
                    "type": "agent_error",
                    "error": "Plan rejected by user. Please provide feedback or a new instruction.",
                },
                room=conversation_id,
            )
            socketio.emit("ai_response", {"type": "done"}, room=conversation_id)


def get_workspace_path(conversation_id, user_id):
    """
    Constructs a path to a conversation-specific workspace, ensuring that the
    path is always based on the conversation's owner, not the current user.
    """
    if not user_id or not conversation_id:
        return None

    # We need to find the conversation's true owner to build the correct path.
    conversation = Conversation.query.get(conversation_id)
    owner_id = conversation.owner_id if conversation else user_id

    # Construct the path using the owner's ID.
    path = os.path.join(
        current_app.config["USER_DATA_DIR"],
        str(owner_id),
        "workspaces",
        str(conversation_id),
    )
    # Create the directory if it's the first time this workspace is being used.
    if not os.path.exists(path):
        os.makedirs(path)
    return path
