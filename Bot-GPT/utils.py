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
    """Constructs a path to a conversation-specific workspace."""
    if not user_id or not conversation_id:
        return None

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        owner_id = user_id
    else:
        owner_id = conversation.owner_id

    path = os.path.join(
        current_app.config["USER_DATA_DIR"],
        str(owner_id),
        "workspaces",
        str(conversation_id),
    )
    if not os.path.exists(path):
        os.makedirs(path)
    return path
