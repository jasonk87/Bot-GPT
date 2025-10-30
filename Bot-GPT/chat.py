import os
import json
import re
import time
import uuid
import requests
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from extensions import socketio
from models import (
    load_conversation, save_conversation, get_all_conversations_for_user,
    check_permission, _save_users, _load_users, add_to_conversation_index,
    find_conversation_owner as find_owner_from_index
)
from tools import call_ollama_chat_stream, handle_tool_call
from prompts import PERSONAS, DEFAULT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT

chat = Blueprint("chat", __name__)

AGENT_SESSIONS = {}

def _get_conversation_path(owner_id, conversation_id):
    """Constructs the file path for a given conversation."""
    return os.path.join(current_app.instance_path, str(owner_id), 'conversations', f'{conversation_id}.json')

def find_conversation_owner(conversation_id):
    """Finds the owner of a conversation using the index."""
    index_path = os.path.join(current_app.instance_path, 'conversation_index.json')
    return find_owner_from_index(index_path, conversation_id)

def initialize_chat(data):
    """
    Initializes a chat session, preparing the conversation object and settings
    using the new file-based system.
    """
    conversation_id = data.get("conversation_id")
    owner_id = current_user.id

    if conversation_id:
        owner_id = find_conversation_owner(conversation_id)
        if not owner_id:
            raise ValueError("Conversation not found.")

        path = _get_conversation_path(owner_id, conversation_id)
        conversation_data = load_conversation(path)

        if not conversation_data or not check_permission(conversation_data, current_user):
            raise ValueError("Conversation not found or you don't have access.")
    else:  # New conversation
        conversation_id = str(uuid.uuid4())
        conversation_data = {
            "id": conversation_id,
            "owner_id": current_user.id,
            "title": "New Chat",
            "participants": [{'user_id': current_user.id, 'role': 'owner'}],
            "messages": []
        }
        path = _get_conversation_path(current_user.id, conversation_id)
        save_conversation(path, conversation_data)

        # Add to the new index
        index_path = os.path.join(current_app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, conversation_id, current_user.id)

    model = data.get("model") or current_user.selected_model
    persona_key = current_user.selected_persona or "default"
    system_prompt = PERSONAS.get(persona_key, {}).get("prompt", DEFAULT_SYSTEM_PROMPT)
    if data.get("agent_mode", False):
        system_prompt = AGENT_SYSTEM_PROMPT

    return model, system_prompt, conversation_data

def handle_ai_response(data):
    """Handles the AI response loop and yields events."""
    try:
        model, system_prompt, conversation_data = initialize_chat(data)
        messages = json.loads(data.get("messages", "[]"))
    except (ValueError, json.JSONDecodeError) as exc:
        yield {"type": "agent_error", "error": str(exc)}
        return

    conversation_id = conversation_data['id']
    yield {"type": "conversation_id", "id": conversation_id}

    agent_mode = data.get("agent_mode", False)
    AGENT_SESSIONS[conversation_id] = {"stop_requested": False}
    max_iterations = 100 if agent_mode else 15

    try:
        for i in range(max_iterations):
            if AGENT_SESSIONS.get(conversation_id, {}).get("stop_requested"):
                yield {"type": "agent_error", "error": "Agent run stopped by user."}
                return

            full_response_content, assistant_message = "", {"role": "assistant", "content": ""}
            try:
                stream = call_ollama_chat_stream(model, messages, system_prompt)
                for chunk in stream:
                    full_response_content += chunk
                    yield {"type": "assistant_chunk", "content": chunk}
            except requests.exceptions.ConnectionError as e:
                yield {"type": "agent_error", "error": f"Could not connect to Ollama: {e}"}
                break

            assistant_message["content"] = full_response_content
            messages.append(assistant_message)
            yield {"type": "assistant_end"}

            tool_calls = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", full_response_content)
            if not tool_calls:
                break

            aggregated_tool_results = []
            for tool_call_str in tool_calls:
                tool_call_id = f"tool_{int(time.time() * 1000)}"
                try:
                    tool_call = json.loads(tool_call_str)
                    yield {"type": "tool_call", "tool_call_id": tool_call_id, "name": tool_call.get("tool"), "params": tool_call.get("parameters")}

                    tool_result, _ = handle_tool_call(tool_call, conversation_data, current_user)

                    if isinstance(tool_result, dict):
                        status = tool_result.get("status")
                        if status in ["canvas_created", "file_written"]:
                            yield {"type": "open_canvas", "filename": tool_result.get("filename") or tool_result.get("path")}
                            yield {"type": "refresh_files", "conversation_id": conversation_id}
                        elif status == "file_updated":
                             yield {"type": "file_updated", "path": tool_result.get("path"), "content": tool_result.get("content")}

                    aggregated_tool_results.append(str(tool_result))
                    yield {"type": "tool_result", "tool_call_id": tool_call_id, "result": tool_result}

                except Exception as e:
                    error_message = f"Error processing tool: {e}"
                    aggregated_tool_results.append(error_message)
                    yield {"type": "tool_error", "tool_call_id": tool_call_id, "error": error_message}

            tool_response_message = "TOOL RESPONSES:\n---\n" + "\n---\n".join(aggregated_tool_results) + "\n---"
            messages.append({"role": "tool", "content": tool_response_message})

    finally:
        if conversation_id in AGENT_SESSIONS:
            del AGENT_SESSIONS[conversation_id]

    if not tool_calls:
        yield from process_final_answer(messages, conversation_data, data.get("canvas_mode", False))

    update_conversation_title(conversation_data, messages)

    messages_to_save = [msg for msg in messages if msg.get("role") in ["user", "assistant"]]
    conversation_data['messages'] = messages_to_save
    path = _get_conversation_path(conversation_data['owner_id'], conversation_id)
    save_conversation(path, conversation_data)

    yield {"type": "done", "title": conversation_data['title']}


@socketio.on("chat_message")
@login_required
def handle_chat_message(data):
    room = data.get("conversation_id") or request.sid
    try:
        for event in handle_ai_response(data):
            emit("ai_response", event, room=room)
    except Exception as exc:
        emit("ai_response", {"type": "agent_error", "error": str(exc)}, room=room)
    finally:
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


def process_final_answer(messages, conversation_data, canvas_mode):
    final_answer_content = messages[-1]["content"]
    if not canvas_mode:
        yield {"type": "final_answer", "content": final_answer_content}
        return

    code_blocks = re.findall(r"```(\w*)\n([\s\S]+?)```", final_answer_content)

    timestamp = int(time.time())
    filename = f"canvas_{timestamp}.py"
    content_to_save = final_answer_content
    if code_blocks:
        content_to_save = max(code_blocks, key=lambda item: len(item[1].split("\n")))[1]

    from tools import write_file
    write_result = write_file(
        path=filename,
        content=content_to_save,
        conversation_id=conversation_data['id'],
        user_id=conversation_data['owner_id'],
    )

    if "successfully" in write_result.get("message", ""):
        yield {"type": "open_canvas", "filename": filename}
        yield {"type": "refresh_files", "conversation_id": conversation_data['id']}
    else:
        yield {"type": "agent_error", "error": f"Failed to save to canvas: {write_result.get('message', '')}"}

    yield {"type": "final_answer", "content": final_answer_content}


def update_conversation_title(conversation_data, messages):
    """Generates a title for a new conversation based on its content."""
    if conversation_data['title'] == "New Chat" and len(messages) >= 2:
        try:
            conversation_text = "\n".join(
                [f"{msg['role'].capitalize()}: {msg['content']}" for msg in messages if msg['role'] in ['user', 'assistant']]
            )

            title_prompt = (
                "Based on the following conversation, please generate a short, descriptive title "
                f"(5 words or less) that summarizes the main topic:\n\n---\n{conversation_text}\n---"
            )

            model = current_user.selected_model or 'qwen:8b'

            title_stream = call_ollama_chat_stream(
                model=model,
                messages=[{'role': 'user', 'content': title_prompt}],
                system_prompt="You are an expert at summarizing conversations. Provide only the title, with no preamble."
            )

            new_title = "".join(list(title_stream)).strip().replace('"', '')

            if new_title and len(new_title) > 1:
                conversation_data['title'] = new_title
        except Exception as e:
            current_app.logger.error(f"Error generating conversation title: {e}")


@socketio.on("stop_agent")
@login_required
def handle_stop_agent(data):
    conversation_id = data.get("conversation_id")
    if conversation_id and conversation_id in AGENT_SESSIONS:
        AGENT_SESSIONS[conversation_id]["stop_requested"] = True
        emit("ai_response", {"type": "agent_error", "error": "Stop signal received. Attempting to halt..."})


@socketio.on("load_conversations")
@login_required
def load_conversations():
    conversations = get_all_conversations_for_user(current_app.instance_path, current_user.id)
    emit("conversations_loaded", conversations)


@socketio.on("load_conversation")
@login_required
def load_conversation_socket(data):
    conversation_id = data.get("conversation_id")
    owner_id = find_conversation_owner(conversation_id)
    if owner_id:
        path = _get_conversation_path(owner_id, conversation_id)
        found_convo = load_conversation(path)
        if found_convo and check_permission(found_convo, current_user):
            role = 'owner' if found_convo['owner_id'] == current_user.id else 'participant'
            emit("conversation_loaded", {"id": found_convo['id'], "messages": found_convo['messages'], "role": role})
            return
    emit("agent_error", {"error": "Conversation not found or access denied."})


@chat.route("/api/settings", methods=["GET", "POST"])
@login_required
def settings_route():
    users_path = os.path.join(current_app.instance_path, 'users.json')
    if request.method == "GET":
        persona_names = {key: value["name"] for key, value in PERSONAS.items()}
        return jsonify({
            "model": current_user.selected_model,
            "persona": current_user.selected_persona,
            "available_personas": persona_names,
        })

    data = request.get_json()
    users = _load_users(users_path)
    user_data = users.get(str(current_user.id))
    if user_data:
        user_data['selected_model'] = data.get("model")
        user_data['selected_persona'] = data.get("persona")
        _save_users(users_path, users)
        current_user.selected_model = data.get("model")
        current_user.selected_persona = data.get("persona")
    return jsonify({"message": "Settings updated successfully"}), 200


@chat.route("/api/models", methods=["GET"])
@login_required
def get_models():
    """Fetches the list of available models from the Ollama API."""
    try:
        ollama_host = current_app.config["OLLAMA_HOST"]
        response = requests.get(f"{ollama_host}/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
        return jsonify([m["name"] for m in models])
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Could not connect to Ollama: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
