import json
import re
import time
import os
import base64
import requests
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room

# Import from app, not extensions
from extensions import socketio

import logging
logging.basicConfig(filename='chat_debug.log', level=logging.DEBUG)


# Import file-based model functions
from models import (
    User,
    load_conversation,
    save_conversation,
    add_to_conversation_index,
    add_user_to_conversation_index,
    find_conversation_owner,
    check_permission,
    get_all_conversations_for_user,
    _load_users,
    _save_users,
)

from tools import call_chat_stream, handle_tool_call
from prompts import PERSONAS, DEFAULT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT
from utils import PLAN_APPROVALS, sanitize_json


chat = Blueprint("chat", __name__)

AGENT_SESSIONS = {}
call_ollama_chat_stream = call_chat_stream


def serialize_agent_session(session):
    """Create a frontend-safe snapshot of an active agent run."""
    if not session or not session.get("running"):
        return None

    return {
        "is_running": True,
        "agent_mode": session.get("agent_mode", False),
        "partial_response": session.get("partial_response", ""),
        "stage": session.get("stage", "thinking"),
        "tool_name": session.get("tool_name"),
        "tool_params": session.get("tool_params"),
        "error": session.get("error"),
    }


def get_conversation_path(owner_id, conversation_id):
    """Helper to construct the path to a conversation file."""
    return os.path.join(
        current_app.instance_path,
        str(owner_id),
        "conversations",
        f"{conversation_id}.json",
    )


def get_conversation_index_path():
    """Helper to construct the path to the conversation index file."""
    return os.path.join(current_app.instance_path, "conversation_index.json")

def get_user_conversation_index_path():
    """Helper to construct the path to the user-conversation index file."""
    return os.path.join(current_app.instance_path, "user_conversation_index.json")

def get_users_path():
    """Helper to construct the path to the users file."""
    return os.path.join(current_app.config["USER_DATA_DIR"], 'users.json')


def initialize_chat(data):
    """
    Initializes a chat session using the file-based storage.
    Returns: model, system_prompt, conversation_dict, conversation_path
    """
    conversation_id = data.get("conversation_id")
    index_path = get_conversation_index_path()
    conversation = None
    conversation_path = None

    if conversation_id and not data.get("is_new_conversation"):
        owner_id = find_conversation_owner(index_path, conversation_id)
        if not owner_id:
            raise ValueError("Conversation not found.")

        conversation_path = get_conversation_path(owner_id, conversation_id)
        conversation = load_conversation(conversation_path)

        if not conversation or not check_permission(conversation, current_user):
            raise ValueError("Conversation not found or you don't have access.")

    else:  # New conversation
        if not conversation_id:
             conversation_id = str(int(time.time() * 1000))
        owner_id = current_user.id
        conversation_path = get_conversation_path(owner_id, conversation_id)

        conversation = {
            "id": conversation_id,
            "title": "New Chat",
            "owner_id": owner_id,
            "participants": [{"user_id": owner_id, "role": "owner"}],
            "messages": [],
            "created_at": time.time(),
        }
        save_conversation(conversation_path, conversation)
        add_to_conversation_index(index_path, conversation_id, owner_id)
        user_convo_index_path = get_user_conversation_index_path()
        add_user_to_conversation_index(user_convo_index_path, owner_id, conversation_id)

    model = data.get("model") or current_user.selected_model
    persona_key = current_user.selected_persona or "default"
    system_prompt = PERSONAS.get(persona_key, {}).get("prompt", DEFAULT_SYSTEM_PROMPT)
    if data.get("agent_mode", False):
        system_prompt = AGENT_SYSTEM_PROMPT

    # --- Memory Injection ---
    try:
        from memory import MemoryManager
        memory = MemoryManager(user_id=current_user.id)
        # We need to set the project memory file path.
        # initialize_chat provides conversation and conversation_path.
        # conversation["owner_id"] is available.
        if conversation:
            memory.set_project_memory_file(conversation["owner_id"], conversation["id"])
            
        memory_context = memory.get_all_context()
        if memory_context:
            system_prompt += f"\n\n=== RECALLED MEMORY ===\n{memory_context}\n=======================\n"
    except Exception as e:
        print(f"Error injecting memory: {e}")
    # ------------------------

    return model, system_prompt, conversation, conversation_path


def handle_ai_response(data):
    """Handles the AI response loop and yields events."""
    print("DEBUG: handle_ai_response triggered")
    try:
        model, system_prompt, conversation, conversation_path = initialize_chat(data)
        messages = json.loads(data.get("messages", "[]"))
        # Ensure the conversation's message history is in sync with the client
        conversation["messages"] = messages
        save_conversation(conversation_path, conversation)
    except (ValueError, json.JSONDecodeError) as exc:
        yield {"type": "agent_error", "error": str(exc)}
        return

    yield {"type": "conversation_id", "id": conversation["id"]}

    agent_mode = data.get("agent_mode", False)
    AGENT_SESSIONS[conversation["id"]] = {
        "stop_requested": False,
        "running": True,
        "agent_mode": agent_mode,
        "partial_response": "",
        "stage": "thinking",
        "tool_name": None,
        "tool_params": None,
        "error": None,
    }
    max_iterations = 100 if agent_mode else 15
    tool_calls = []

    try:
        for i in range(max_iterations):
            if AGENT_SESSIONS.get(conversation["id"], {}).get("stop_requested"):
                yield {"type": "agent_error", "error": "Agent run stopped by user."}
                break

            full_response_content = ""
            assistant_message = {"role": "assistant", "content": ""}

            try:
                print(f"DEBUG: Calling AI Stream with model {model}")
                stream = call_ollama_chat_stream(model, conversation["messages"], system_prompt)
                for chunk in stream:
                    full_response_content += chunk
                    AGENT_SESSIONS[conversation["id"]]["partial_response"] = full_response_content
                    AGENT_SESSIONS[conversation["id"]]["stage"] = "answering"
                    yield {"type": "assistant_chunk", "content": chunk}
            except Exception as e:
                AGENT_SESSIONS[conversation["id"]]["stage"] = "error"
                AGENT_SESSIONS[conversation["id"]]["error"] = str(e)
                yield {"type": "agent_error", "error": f"Could not connect to AI: {e}"}
                break

            assistant_message["content"] = full_response_content
            conversation["messages"].append(assistant_message)
            AGENT_SESSIONS[conversation["id"]]["partial_response"] = full_response_content
            AGENT_SESSIONS[conversation["id"]]["stage"] = "thinking"
            yield {"type": "assistant_end"}

            tool_calls = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", full_response_content)
            if not tool_calls:
                break

            aggregated_tool_results = []
            for tool_call_str in tool_calls:
                tool_call_id = f"tool_{int(time.time() * 1000)}"
                try:
                    tool_call_str = sanitize_json(tool_call_str)
                    tool_call = json.loads(tool_call_str)
                    AGENT_SESSIONS[conversation["id"]]["stage"] = "tool_call"
                    AGENT_SESSIONS[conversation["id"]]["tool_name"] = tool_call.get("tool")
                    AGENT_SESSIONS[conversation["id"]]["tool_params"] = tool_call.get("parameters")
                    yield {"type": "tool_call", "tool_call_id": tool_call_id, "name": tool_call.get("tool"), "params": tool_call.get("parameters")}

                    tool_result, _ = handle_tool_call(tool_call, conversation, current_user)

                    if isinstance(tool_result, dict):
                        status = tool_result.get("status")
                        if status == "canvas_created" or (status == "file_written" and tool_call.get("tool") in ["create_and_open_canvas", "write_file"]):
                            yield {"type": "open_canvas", "filename": tool_result.get("path") or tool_result.get("filename")}
                        elif status == "file_written":
                            yield {"type": "file_updated", "path": tool_result.get("path"), "content": tool_result.get("content")}

                    aggregated_tool_results.append(str(tool_result))
                    AGENT_SESSIONS[conversation["id"]]["stage"] = "after_tool"
                    yield {"type": "tool_result", "tool_call_id": tool_call_id, "result": tool_result}

                except Exception as e:
                    error_message = f"Error processing tool: {e}"
                    aggregated_tool_results.append(error_message)
                    AGENT_SESSIONS[conversation["id"]]["stage"] = "tool_error"
                    AGENT_SESSIONS[conversation["id"]]["error"] = error_message
                    yield {"type": "tool_error", "tool_call_id": tool_call_id, "error": error_message}

            tool_response_message = "TOOL RESPONSES:\n---\n" + "\n---\n".join(aggregated_tool_results) + "\n---"
            conversation["messages"].append({"role": "tool", "content": tool_response_message})

            # Capture screen after tools to see the effect
            # --- AUTOMATIC SCREEN CAPTURE AFTER TOOLS REMOVED ---
            # The agent can now decide to call capture_screen if it needs to see the result.
            pass

        else: # This else belongs to the for loop, executes if loop finishes without break
            if agent_mode:
                yield {"type": "agent_error", "error": "Agent reached maximum iterations."}

    finally:
        if conversation["id"] in AGENT_SESSIONS:
            AGENT_SESSIONS[conversation["id"]]["running"] = False
            del AGENT_SESSIONS[conversation["id"]]

    # Process final answer only if no tool calls were made in the last iteration
    if not tool_calls:
        yield from process_final_answer(conversation, conversation_path, data.get("canvas_mode", False))

    update_conversation_title(conversation, conversation_path)

    messages_to_save = [msg for msg in conversation["messages"] if msg.get("role") in ["user", "assistant"]]
    conversation["messages"] = messages_to_save

    save_conversation(conversation_path, conversation)

    yield {"type": "done", "title": conversation.get("title", "New Chat")}


@socketio.on("chat_message")
@login_required
def handle_chat_message(data):
    """Handles a chat message received over WebSocket."""
    print("DEBUG: handle_chat_message triggered")
    room = data.get("conversation_id") or request.sid
    
    room = data.get("conversation_id") or request.sid
    
    # --- AUTOMATIC SCREEN CAPTURE REMOVED ---
    captured_screen_path = None 
    # ----------------------------------------

    # Pre-process images in the latest message
    try:
        messages = json.loads(data.get("messages", "[]"))
        if messages:
            # Always enter this block to handle potential screen capture even if no user-uploaded images
            # This is a change from: if messages and "images" in messages[-1]:
            
            # This is a new message with images
            last_msg = messages[-1]
            images_data = last_msg.pop("images", []) # Remove base64 data from memory/JSON

            conversation_id = data.get("conversation_id")
            if not conversation_id:
                 # Should have been created by initialize_chat, but if new...
                 # We can't save images easily without an ID.
                 # Let's rely on handle_ai_response's initialize_chat to create it,
                 # but we need to save images BEFORE that to clear base64.
                 # Actually, handle_ai_response calls initialize_chat first.
                 pass

            # We need the owner ID to save files.
            # Quick lookup or assume current user if new.
            index_path = get_conversation_index_path()
            owner_id = find_conversation_owner(index_path, conversation_id)
            if not owner_id and not conversation_id:
                 owner_id = current_user.id
            elif not owner_id:
                 owner_id = current_user.id # Fallback

            # If conversation_id is empty, handle_ai_response will generate one.
            # But we need to save images now.
            # Strategy: if no ID, generate one now and pass it back to data.
            if not conversation_id:
                conversation_id = str(int(time.time() * 1000))
                data["conversation_id"] = conversation_id
                data["is_new_conversation"] = True
            
            # If there was no image data in the message, we still need to process the screen capture
            # But the block above (lines 217-270) only runs if "images" is in messages[-1]. 
            # We need to handle the case where the user sent TEXT only, but we still want to attach our screenshot.
            pass # Continue to image processing (loop below will handle empty images_data)

            image_paths = []
            images_dir = os.path.join(current_app.instance_path, str(owner_id), "conversations", conversation_id, "images")
            os.makedirs(images_dir, exist_ok=True)

            for idx, img_base64 in enumerate(images_data):
                if "," in img_base64:
                    header, encoded = img_base64.split(",", 1)
                else:
                    encoded = img_base64

                file_ext = "png" # Default
                if "image/jpeg" in img_base64: file_ext = "jpg"
                if "image/webp" in img_base64: file_ext = "webp"

                filename = f"img_{int(time.time())}_{idx}.{file_ext}"
                filepath = os.path.join(images_dir, filename)

                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(encoded))

                image_paths.append(filepath)

            last_msg["images"] = image_paths # Replace base64 with paths
            
            # --- AUTOMATIC SCREEN CAPTURE REMOVED ---
            # (Logic for merging captured_screen_path was here)
            # ----------------------------------------
            
            data["messages"] = json.dumps(messages) # Update data payload

    except Exception as e:
        current_app.logger.error(f"Error processing images: {e}")
        emit("ai_response", {"type": "agent_error", "error": f"Image upload failed: {e}"}, room=room)
        return

    try:
        messages = json.loads(data["messages"])
        last_user_message = messages[-1]["content"] if messages else ""
    except (KeyError, TypeError, json.JSONDecodeError):
        emit("ai_response", {"type": "agent_error", "error": "Invalid message payload"}, room=room)
        emit("ai_response", {"type": "done"}, room=room)
        return

    emit("ai_response", {"type": "user_message", "content": last_user_message}, room=room, include_self=False)

    done_sent = False
    try:
        for event in handle_ai_response(data):
            print(f"DEBUG: Emitting event: {event}")
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
    """Adds the current user to a Socket.IO room for conversation updates."""
    room = data.get("room")
    if room:
        join_room(room)


@socketio.on("leave")
@login_required
def handle_leave_room(data):
    """Removes the current user from a Socket.IO room when they leave a chat."""
    room = data.get("room")
    if room:
        leave_room(room)


@socketio.on("connect")
def handle_connect():
    print(f"DEBUG: Socket client connected: {request.sid}")


def process_final_answer(conversation, conversation_path, canvas_mode):
    """
    Processes the final answer. If in canvas_mode, saves the largest code block to a file.
    """
    if not conversation.get("messages"):
        return

    final_assistant_message = next(
        (msg for msg in reversed(conversation["messages"]) if msg.get("role") == "assistant"),
        None,
    )
    if not final_assistant_message:
        return

    final_answer_content = final_assistant_message["content"]
    if not canvas_mode:
        yield {"type": "final_answer", "content": final_answer_content}
        return

    code_blocks = re.findall(r"```(\w*)\n([\s\S]+?)```", final_answer_content)
    if not code_blocks:
        content_to_save = re.sub(r"<think>[\s\S]*?<\/think>", "", final_answer_content).strip()
        file_extension = "md"
    else:
        largest_block = max(code_blocks, key=lambda item: len(item[1].split("\n")))
        language, content_to_save = largest_block[0].lower(), largest_block[1].strip()
        file_extension = {"python": "py", "javascript": "js", "html": "html", "css": "css", "json": "json", "sql": "sql", "shell": "sh", "bash": "sh"}.get(language, "txt")

    timestamp = int(time.time())
    filename = f"canvas_{timestamp}.{file_extension}"

    from tools import write_file
    write_result = write_file(path=filename, content=content_to_save, conversation_id=conversation["id"], user_id=conversation["owner_id"])

    if "successfully" in write_result.get("message", ""):
        yield {"type": "open_canvas", "filename": filename}
    else:
        yield {"type": "agent_error", "error": f"Failed to save to canvas: {write_result.get('message', '')}"}

    yield {"type": "final_answer", "content": final_answer_content}


def update_conversation_title(conversation, conversation_path):
    """Updates the conversation title if it's a new chat."""
    if conversation.get("title") == "New Chat" and len(conversation.get("messages", [])) >= 2:
        try:
            user_message = conversation["messages"][0]["content"]
            assistant_message = next((m["content"] for m in reversed(conversation["messages"]) if m["role"] == "assistant"), "")

            cleaned_content = re.sub(r"<think>[\s\S]*?</think>", "", assistant_message).strip()
            title_prompt = f"Based on the following exchange, create a very short, concise title (5 words or less).\n\nUser: {user_message}\nAssistant: {cleaned_content}\n\nTitle:"

            # Use the shared function instead of direct requests
            model = current_user.selected_model or "gemini-2.0-flash"
            messages = [{"role": "user", "content": title_prompt}]

            content = ""
            for chunk in call_ollama_chat_stream(model, messages, "You are a helpful assistant."):
                 content += chunk

            raw_title = content.strip()
            cleaned_title = re.sub(r"<think>[\s\S]*?</think>", "", raw_title).strip().replace('"', "")

            if cleaned_title:
                conversation["title"] = cleaned_title
                save_conversation(conversation_path, conversation)
        except Exception as e:
            current_app.logger.warning(f"Could not auto-generate title: {e}")


@socketio.on("stop_agent")
@login_required
def handle_stop_agent(data):
    """Handles a request to stop a running agent."""
    conversation_id = data.get("conversation_id")
    if conversation_id and conversation_id in AGENT_SESSIONS:
        AGENT_SESSIONS[conversation_id]["stop_requested"] = True
        emit("ai_response", {"type": "agent_error", "error": "Stop signal received. Attempting to halt..."}, room=conversation_id)


@socketio.on("user_response")
@login_required
def handle_user_response(data):
    """Handles user approval/rejection of plans."""
    conversation_id = data.get("conversation_id")
    response = data.get("response")

    if conversation_id and response:
        # Update the shared state dictionary to unblock the set_plan tool
        PLAN_APPROVALS[conversation_id] = response
        print(f"DEBUG: Received user response '{response}' for conversation {conversation_id}")



@socketio.on("load_conversations")
@login_required
def load_conversations_socket():
    """Loads all conversations for the current user via WebSocket."""
    conversations = get_all_conversations_for_user(current_app.instance_path, current_user.id)
    emit("conversations_loaded", conversations)


@socketio.on("load_conversation")
@login_required
def load_conversation_socket(data):
    """Loads a specific conversation's messages via WebSocket."""
    conversation_id = data.get("conversation_id")
    index_path = get_conversation_index_path()
    owner_id = find_conversation_owner(index_path, conversation_id)

    if not owner_id:
        emit("agent_error", {"error": "Conversation not found"})
        return

    conversation_path = get_conversation_path(owner_id, conversation_id)
    conversation = load_conversation(conversation_path)

    if conversation and check_permission(conversation, current_user):
        participant = next((p for p in conversation.get("participants", []) if p["user_id"] == current_user.id), None)
        emit(
            "conversation_loaded",
            {
                "id": conversation["id"],
                "messages": conversation.get("messages", []),
                "role": participant["role"] if participant else "participant",
                "active_run": serialize_agent_session(AGENT_SESSIONS.get(conversation_id)),
            },
        )
    else:
        emit("agent_error", {"error": "You don't have access to this conversation"})


@chat.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    """Gets user settings."""
    persona_names = {key: value["name"] for key, value in PERSONAS.items()}
    return jsonify({
        "model": current_user.selected_model,
        "persona": current_user.selected_persona,
        "available_personas": persona_names,
    })


@chat.route("/api/settings", methods=["POST"])
@login_required
def update_settings():
    """Updates user settings in the file-based system."""
    data = request.get_json()
    path = get_users_path()
    users = _load_users(path)
    user_data = users.get(str(current_user.id))

    if user_data:
        user_data['selected_model'] = data.get('model', user_data.get('selected_model'))
        user_data['selected_persona'] = data.get('persona', user_data.get('selected_persona'))
        _save_users(path, users)
        return jsonify({"message": "Settings updated successfully"}), 200

    return jsonify({"message": "User not found"}), 404


@chat.route("/api/models")
@login_required
def get_models():
    """Fetches available models from local Ollama."""
    models = []
    try:
        # Fetch from local Ollama API
        ollama_host = current_app.config.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"
            
        print(f"DEBUG: Fetching models from {ollama_host}/api/tags")
        response = requests.get(f"{ollama_host}/api/tags", timeout=10)
        if response.ok:
            ollama_data = response.json()
            for model_info in ollama_data.get("models", []):
                models.append({
                    "name": model_info.get("name"),
                    "modified_at": model_info.get("modified_at"),
                    "size": model_info.get("size")
                })
    except Exception as e:
        current_app.logger.warning(f"Could not reach Ollama: {e}")

    # Fallback to current selected model if no models found to ensure picker isn't empty
    if not models and current_user.selected_model:
        models.append({
            "name": current_user.selected_model,
            "modified_at": "unknown",
            "size": 0
        })

    return jsonify(models)



@chat.route("/api/chat")
@login_required
def chat_proxy():
    """(DEPRECATED) Orchestrates the AI response loop via HTTP streaming."""
    data = {
        "messages": request.args.get("messages", "[]"),
        "model": request.args.get("model"),
        "conversation_id": request.args.get("conversation_id"),
        "agent_mode": request.args.get("agent_mode", "false").lower() == 'true',
        "canvas_mode": request.args.get("canvas_mode", "false").lower() == 'true',
    }

    def event_stream():
        with current_app.app_context():
            for event in handle_ai_response(data):
                yield f"data: {json.dumps(event)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


@chat.route('/api/plan_response', methods=['POST'])
@login_required
def handle_plan_response_api():
    """
    HTTP Endpoint to handle plan approval.
    Bypasses Socket.IO to avoid deadlocking the single-client event loop.
    """
    data = request.get_json()
    conversation_id = data.get("conversation_id")
    response = data.get("response")

    if conversation_id and response:
        # Update the shared state dictionary directly
        PLAN_APPROVALS[conversation_id] = response
        print(f"DEBUG: Received HTTP plan response '{response}' for {conversation_id}")
        return jsonify({"status": "success"})

    return jsonify({"error": "Invalid parameters"}), 400
