import json
import requests
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user

from extensions import socketio
from models import _load_users, _save_users
from prompts import PERSONAS
from shared_paths import get_users_path
from tools import handle_tool_call, call_chat_stream, write_file
from utils import PLAN_APPROVALS, sanitize_json

from chat_state import AGENT_SESSIONS, serialize_agent_session
from chat_persistence import initialize_chat
from chat_title import update_conversation_title as _update_conversation_title
from chat_ai import handle_ai_response as _handle_ai_response
from chat_ai import get_depth_routing_metrics as _get_depth_routing_metrics
from chat_socket import register_socket_handlers

chat = Blueprint("chat", __name__)
call_ollama_chat_stream = call_chat_stream


def update_conversation_title(conversation, conversation_path, model=None):
    return _update_conversation_title(conversation, conversation_path, call_ollama_chat_stream, model=model)


def handle_ai_response(data):
    return _handle_ai_response(
        data,
        initialize_chat=initialize_chat,
        call_stream=call_ollama_chat_stream,
        handle_tool_call=handle_tool_call,
        sanitize_json=sanitize_json,
        agent_sessions=AGENT_SESSIONS,
        update_conversation_title=update_conversation_title,
        write_file=write_file,
    )


register_socket_handlers(
    socketio,
    agent_sessions=AGENT_SESSIONS,
    serialize_agent_session=serialize_agent_session,
    handle_ai_response=handle_ai_response,
    plan_approvals=PLAN_APPROVALS,
)


@chat.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    persona_names = {key: value["name"] for key, value in PERSONAS.items()}
    return jsonify({
        "model": current_user.selected_model,
        "persona": current_user.selected_persona,
        "response_mode_preference": getattr(current_user, "response_mode_preference", "auto"),
        "available_personas": persona_names,
    })


@chat.route("/api/settings", methods=["POST"])
@login_required
def update_settings():
    data = request.get_json()
    users = _load_users(get_users_path())
    user_data = users.get(str(current_user.id))
    if user_data:
        user_data["selected_model"] = data.get("model", user_data.get("selected_model"))
        user_data["selected_persona"] = data.get("persona", user_data.get("selected_persona"))
        user_data["response_mode_preference"] = data.get("response_mode_preference", user_data.get("response_mode_preference", "auto"))
        _save_users(get_users_path(), users)
        return jsonify({"message": "Settings updated successfully"}), 200
    return jsonify({"message": "User not found"}), 404


@chat.route("/api/models")
@login_required
def get_models():
    models = []
    try:
        ollama_host = current_app.config.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"
        response = requests.get(f"{ollama_host}/api/tags", timeout=10)
        if response.ok:
            for model_info in response.json().get("models", []):
                models.append({
                    "name": model_info.get("name"),
                    "modified_at": model_info.get("modified_at"),
                    "size": model_info.get("size"),
                })
    except Exception as e:
        current_app.logger.warning(f"Could not reach Ollama: {e}")

    if not models and current_user.selected_model:
        models.append({"name": current_user.selected_model, "modified_at": "unknown", "size": 0})
    return jsonify(models)


@chat.route("/api/chat")
@login_required
def chat_proxy():
    data = {
        "messages": request.args.get("messages", "[]"),
        "model": request.args.get("model"),
        "conversation_id": request.args.get("conversation_id"),
        "agent_mode": request.args.get("agent_mode", "false").lower() == "true",
        "canvas_mode": request.args.get("canvas_mode", "false").lower() == "true",
    }

    def event_stream():
        with current_app.app_context():
            for event in handle_ai_response(data):
                yield f"data: {json.dumps(event)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


@chat.route('/api/plan_response', methods=['POST'])
@login_required
def handle_plan_response_api():
    data = request.get_json()
    conversation_id = data.get("conversation_id")
    response = data.get("response")
    if conversation_id and response:
        PLAN_APPROVALS[conversation_id] = response
        return jsonify({"status": "success"})
    return jsonify({"error": "Invalid parameters"}), 400


@chat.route("/api/depth_metrics", methods=["GET"])
@login_required
def get_depth_metrics():
    return jsonify(_get_depth_routing_metrics())
