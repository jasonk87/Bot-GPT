import base64
import json
import os
import time

from flask import current_app, request
from flask_login import current_user, login_required
try:
    from flask_socketio import emit, join_room, leave_room
except ImportError:  # pragma: no cover - fallback when socketio dependency is absent
    def emit(*args, **kwargs):
        return None

    def join_room(*args, **kwargs):
        return None

    def leave_room(*args, **kwargs):
        return None

from models import (
    load_conversation,
    check_permission,
    get_all_conversations_for_user,
    find_conversation_owner,
)
from shared_paths import get_conversation_index_path, get_conversation_path


def register_socket_handlers(socketio, *, agent_sessions, serialize_agent_session, handle_ai_response, plan_approvals):
    @socketio.on("chat_message")
    @login_required
    def handle_chat_message(data):
        room = data.get("conversation_id") or request.sid
        try:
            messages = json.loads(data.get("messages", "[]"))
            if messages:
                last_msg = messages[-1]
                images_data = last_msg.pop("images", [])
                conversation_id = data.get("conversation_id")
                owner_id = find_conversation_owner(get_conversation_index_path(), conversation_id) if conversation_id else current_user.id
                if not conversation_id:
                    conversation_id = str(int(time.time() * 1000))
                    data["conversation_id"] = conversation_id
                    data["is_new_conversation"] = True
                images_dir = os.path.join(current_app.instance_path, str(owner_id), "conversations", conversation_id, "images")
                os.makedirs(images_dir, exist_ok=True)
                image_paths = []
                for idx, img_base64 in enumerate(images_data):
                    encoded = img_base64.split(",", 1)[1] if "," in img_base64 else img_base64
                    file_ext = "jpg" if "image/jpeg" in img_base64 else "webp" if "image/webp" in img_base64 else "png"
                    filepath = os.path.join(images_dir, f"img_{int(time.time())}_{idx}.{file_ext}")
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(encoded))
                    image_paths.append(filepath)
                last_msg["images"] = image_paths
                data["messages"] = json.dumps(messages)
        except Exception as e:
            current_app.logger.error(f"Error processing images: {e}")
            emit("ai_response", {"type": "agent_error", "error": f"Image upload failed: {e}"}, room=room)
            return

        try:
            parsed_messages = json.loads(data["messages"])
            last_user_message = parsed_messages[-1]["content"] if parsed_messages else ""
        except (KeyError, TypeError, json.JSONDecodeError):
            emit("ai_response", {"type": "agent_error", "error": "Invalid message payload"}, room=room)
            emit("ai_response", {"type": "done"}, room=room)
            return

        emit("ai_response", {"type": "user_message", "content": last_user_message}, room=room, include_self=False)
        done_sent = False
        try:
            for event in handle_ai_response(data):
                emit("ai_response", event, room=room)
                if event.get("type") == "done":
                    done_sent = True
        except Exception as exc:
            current_app.logger.error(f"Error in chat handler: {exc}", exc_info=True)
            emit("ai_response", {"type": "agent_error", "error": str(exc)}, room=room)
        finally:
            if not done_sent:
                emit("ai_response", {"type": "done"}, room=room)

    @socketio.on("join")
    @login_required
    def handle_join_room(data):
        room = data.get("room")
        if room:
            join_room(room)

    @socketio.on("leave")
    @login_required
    def handle_leave_room(data):
        room = data.get("room")
        if room:
            leave_room(room)

    @socketio.on("stop_agent")
    @login_required
    def handle_stop_agent(data):
        conversation_id = data.get("conversation_id")
        if conversation_id and conversation_id in agent_sessions:
            agent_sessions[conversation_id]["stop_requested"] = True
            emit("ai_response", {"type": "agent_error", "error": "Stop signal received. Attempting to halt..."}, room=conversation_id)

    @socketio.on("user_response")
    @login_required
    def handle_user_response(data):
        conversation_id = data.get("conversation_id")
        response = data.get("response")
        if conversation_id and response:
            plan_approvals[conversation_id] = response

    @socketio.on("load_conversations")
    @login_required
    def load_conversations_socket():
        conversations = get_all_conversations_for_user(current_app.instance_path, current_user.id)
        emit("conversations_loaded", conversations)

    @socketio.on("load_conversation")
    @login_required
    def load_conversation_socket(data):
        conversation_id = data.get("conversation_id")
        owner_id = find_conversation_owner(get_conversation_index_path(), conversation_id)
        if not owner_id:
            emit("agent_error", {"error": "Conversation not found"})
            return
        conversation = load_conversation(get_conversation_path(owner_id, conversation_id))
        if conversation and check_permission(conversation, current_user):
            participant = next((p for p in conversation.get("participants", []) if p["user_id"] == current_user.id), None)
            emit("conversation_loaded", {
                "id": conversation["id"],
                "messages": conversation.get("messages", []),
                "role": participant["role"] if participant else "participant",
                "active_run": serialize_agent_session(agent_sessions.get(conversation_id)),
            })
        else:
            emit("agent_error", {"error": "You don't have access to this conversation"})
