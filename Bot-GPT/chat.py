import json
import re
import time
import requests
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from extensions import db, socketio
from models import Conversation, ConversationParticipant, Message
from tools import call_ollama_chat_stream, handle_tool_call
from prompts import PERSONAS, DEFAULT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT

chat = Blueprint("chat", __name__)

AGENT_SESSIONS = {}


def initialize_chat(data):
    """
    Initializes a chat session, preparing the conversation object and settings.
    Note: This function no longer loads message history. The history is taken
    directly from the client's payload in `handle_ai_response`.
    """
    conversation_id = data.get("conversation_id")

    if conversation_id:
        conversation = Conversation.query.get(conversation_id)
        if not conversation or not conversation.check_permission(current_user):
            raise ValueError("Conversation not found or you don't have access.")
    else:  # New conversation
        conversation = Conversation(title="New Chat", owner_id=current_user.id)
        db.session.add(conversation)
        db.session.flush()  # Ensure the conversation gets an ID
        conversation_id = conversation.id
        participant = ConversationParticipant(
            user_id=current_user.id, conversation_id=conversation.id, role="owner"
        )
        db.session.add(participant)
        db.session.commit()

    model = data.get("model") or current_user.selected_model
    persona_key = current_user.selected_persona or "default"
    system_prompt = PERSONAS.get(persona_key, {}).get("prompt", DEFAULT_SYSTEM_PROMPT)
    if data.get("agent_mode", False):
        system_prompt = AGENT_SYSTEM_PROMPT

    return model, system_prompt, conversation


def handle_ai_response(data):
    """Handles the AI response loop and yields events."""
    try:
        model, system_prompt, conversation = initialize_chat(data)
        messages = json.loads(data.get("messages", "[]"))
    except (ValueError, json.JSONDecodeError) as exc:
        yield {"type": "agent_error", "error": str(exc)}
        return

    yield {"type": "conversation_id", "id": conversation.id}

    agent_mode = data.get("agent_mode", False)
    AGENT_SESSIONS[conversation.id] = {"stop_requested": False}
    max_iterations = 100 if agent_mode else 15

    tool_match = None

    try:
        for i in range(max_iterations):
            if AGENT_SESSIONS.get(conversation.id, {}).get("stop_requested"):
                yield {"type": "agent_error", "error": "Agent run stopped by user."}
                break

            full_response_content, assistant_message = "", {
                "role": "assistant",
                "content": "",
            }
            try:
                stream = call_ollama_chat_stream(model, messages, system_prompt)
                for chunk in stream:
                    full_response_content += chunk
                    yield {"type": "assistant_chunk", "content": chunk}
            except requests.exceptions.ConnectionError as e:
                yield {
                    "type": "agent_error",
                    "error": f"Could not connect to Ollama: {e}",
                }
                break

            assistant_message["content"] = full_response_content
            messages.append(assistant_message)
            yield {"type": "assistant_end"}

            tool_calls = re.findall(
                r"```json\s*(\{[\s\S]*?\})\s*```", full_response_content
            )
            if not tool_calls:
                break  # No tools to call, proceed to final answer

            aggregated_tool_results = []
            for tool_call_str in tool_calls:
                tool_call_id = f"tool_{int(time.time() * 1000)}"
                try:
                    tool_call = json.loads(tool_call_str)
                    yield {
                        "type": "tool_call",
                        "tool_call_id": tool_call_id,
                        "name": tool_call.get("tool"),
                        "params": tool_call.get("parameters"),
                    }

                    tool_result, _ = handle_tool_call(
                        tool_call, conversation, current_user
                    )

                    if isinstance(tool_result, dict):
                        status = tool_result.get("status")
                        if status == "canvas_created":
                            yield {
                                "type": "open_canvas",
                                "filename": tool_result.get("filename"),
                            }
                        elif status == "file_written":
                            yield {
                                "type": "file_updated",
                                "path": tool_result.get("path"),
                                "content": tool_result.get("content"),
                            }

                    aggregated_tool_results.append(str(tool_result))
                    yield {
                        "type": "tool_result",
                        "tool_call_id": tool_call_id,
                        "result": tool_result,
                    }

                except Exception as e:
                    error_message = f"Error processing tool: {e}"
                    aggregated_tool_results.append(error_message)
                    yield {
                        "type": "tool_error",
                        "tool_call_id": tool_call_id,
                        "error": error_message,
                    }

            # Append a single aggregated tool response to the message history
            tool_response_message = "TOOL RESPONSES:\n---\n" + "\n---\n".join(aggregated_tool_results) + "\n---"
            messages.append({"role": "tool", "content": tool_response_message})

    finally:
        if conversation.id in AGENT_SESSIONS:
            del AGENT_SESSIONS[conversation.id]

    if not tool_calls:
        yield from process_final_answer(
            messages, conversation, data.get("canvas_mode", False)
        )

    update_conversation_title(conversation, messages)

    # Filter out any tool-related messages before saving
    messages_to_save = [
        msg for msg in messages if msg.get("role") in ["user", "assistant"]
    ]

    # Replace the stored messages with the latest history
    conversation.messages.clear()
    for msg in messages_to_save:
        new_message = Message(
            conversation_id=conversation.id, role=msg["role"], content=msg["content"]
        )
        db.session.add(new_message)
    db.session.commit()

    yield {"type": "done", "title": conversation.title}


@socketio.on("chat_message")
@login_required
def handle_chat_message(data):
    """Handles a chat message received over WebSocket."""
    room = data.get("conversation_id") or request.sid
    try:
        messages = json.loads(data["messages"])
        last_user_message = messages[-1]["content"] if messages else ""
    except (KeyError, TypeError, json.JSONDecodeError):
        emit(
            "ai_response",
            {"type": "agent_error", "error": "Invalid message payload"},
            room=room,
        )
        emit("ai_response", {"type": "done"}, room=room)
        return

    emit(
        "ai_response",
        {"type": "user_message", "content": last_user_message},
        room=room,
        include_self=False,
    )
    done_sent = False
    try:
        for event in handle_ai_response(data):
            emit("ai_response", event, room=room)
            if event.get("type") == "done":
                done_sent = True
    except Exception as exc:
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


def process_final_answer(messages, conversation, canvas_mode):
    """
    Processes the final answer from the AI. If in canvas_mode, it finds the
    largest code block, saves it to a file, and signals the frontend to open it.
    """
    final_answer_content = messages[-1]["content"]
    if not canvas_mode:
        yield {"type": "final_answer", "content": final_answer_content}
        return

    # Find all code blocks and identify the largest one
    code_blocks = re.findall(r"```(\w*)\n([\s\S]+?)```", final_answer_content)
    if not code_blocks:
        # If no code blocks, save the whole message as markdown
        content_to_save = re.sub(
            r"<think>[\s\S]*?<\/think>", "", final_answer_content
        ).strip()
        file_extension = "md"
    else:
        # Find the code block with the most lines
        largest_block = max(code_blocks, key=lambda item: len(item[1].split("\n")))
        language = largest_block[0].lower()
        content_to_save = largest_block[1].strip()
        file_extension = {
            "python": "py",
            "javascript": "js",
            "html": "html",
            "css": "css",
            "json": "json",
            "sql": "sql",
            "shell": "sh",
            "bash": "sh",
        }.get(language, "txt")

    # Proceed with saving the determined content
    timestamp = int(time.time())
    filename = f"canvas_{timestamp}.{file_extension}"

    from tools import write_file

    # Note: we pass owner_id to ensure the workspace path is correct
    write_result = write_file(
        path=filename,
        content=content_to_save,
        conversation_id=conversation.id,
        user_id=conversation.owner_id,
    )

    if "successfully" in write_result.get("message", ""):
        yield {"type": "open_canvas", "filename": filename}
        # The write_file tool now emits 'refresh_files' directly
    else:
        yield {
            "type": "agent_error",
            "error": f"Failed to save to canvas: {write_result.get('message', '')}",
        }

    yield {"type": "final_answer", "content": final_answer_content}


def update_conversation_title(conversation, messages):
    """Updates the conversation title if it's a new chat."""
    if conversation.title == "New Chat" and len(messages) >= 2:
        try:
            final_ai_message = next(
                (m["content"] for m in reversed(messages) if m["role"] == "assistant"),
                "",
            )
            cleaned_content = re.sub(
                r"<think>[\s\S]*?</think>", "", final_ai_message
            ).strip()
            title_prompt = f"Based on the following exchange, create a very short, concise title (5 words or less).\n\nUser: {messages[0]['content']}\nAssistant: {cleaned_content}\n\nTitle:"
            title_model = "llama3.2:latest"
            response = requests.post(
                f"{current_app.config['OLLAMA_HOST']}/api/chat",
                json={
                    "model": title_model,
                    "messages": [{"role": "user", "content": title_prompt}],
                    "stream": False,
                },
                timeout=180,
            )
            response.raise_for_status()
            raw_title = response.json().get("message", {}).get("content", "").strip()
            cleaned_title = (
                re.sub(r"<think>[\s\S]*?</think>", "", raw_title)
                .strip()
                .replace('"', "")
            )
            if cleaned_title:
                conversation.title = cleaned_title
                db.session.commit()
        except requests.exceptions.RequestException as e:
            print(f"Could not auto-generate title: {e}")


@socketio.on("stop_agent")
@login_required
def handle_stop_agent(data):
    """Handles a request to stop a running agent."""
    conversation_id = data.get("conversation_id")
    if conversation_id and conversation_id in AGENT_SESSIONS:
        AGENT_SESSIONS[conversation_id]["stop_requested"] = True
        emit(
            "ai_response",
            {
                "type": "agent_error",
                "error": "Stop signal received. Attempting to halt...",
            },
        )


@socketio.on("load_conversations")
@login_required
def load_conversations():
    """Loads all conversations for the current user."""
    participants = ConversationParticipant.query.filter_by(
        user_id=current_user.id
    ).all()
    conversations = []
    for p in participants:
        conversations.append(
            {"id": p.conversation.id, "title": p.conversation.title, "role": p.role}
        )
    emit("conversations_loaded", conversations)


@socketio.on("load_conversation")
@login_required
def load_conversation(data):
    """Loads a specific conversation's messages."""
    conversation_id = data.get("conversation_id")
    conversation = Conversation.query.filter_by(id=conversation_id).first()

    if conversation and conversation.check_permission(current_user):
        messages = [
            {"role": msg.role, "content": msg.content} for msg in conversation.messages
        ]

        participant = ConversationParticipant.query.filter_by(
            user_id=current_user.id, conversation_id=conversation_id
        ).first()

        emit(
            "conversation_loaded",
            {
                "id": conversation.id,
                "messages": messages,
                "role": participant.role if participant else "participant",
            },
        )


@chat.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    persona_names = {key: value["name"] for key, value in PERSONAS.items()}
    return jsonify(
        {
            "model": current_user.selected_model,
            "persona": current_user.selected_persona,
            "available_personas": persona_names,
        }
    )


@chat.route("/api/settings", methods=["POST"])
@login_required
def update_settings():
    data = request.get_json()
    current_user.selected_model = data.get("model")
    current_user.selected_persona = data.get("persona")
    db.session.commit()
    return jsonify({"message": "Settings updated successfully"}), 200


@chat.route("/api/models")
@login_required
def get_models():
    """Fetches the available models from the Ollama host."""
    try:
        ollama_host = current_app.config["OLLAMA_HOST"]
        response = requests.get(f"{ollama_host}/api/tags")
        response.raise_for_status()
        return jsonify(response.json().get("models", []))
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502


@chat.route("/api/chat")
@login_required
def chat_proxy():
    """(DEPRECATED) Orchestrates the ReAct loop for conversational AI."""
    messages_str = request.args.get("messages", "[]")
    model = request.args.get("model")
    conversation_id_arg = request.args.get("conversation_id")

    data = {
        "messages": messages_str,
        "model": model,
        "conversation_id": conversation_id_arg,
    }

    def event_stream():
        with current_app.app_context():
            for event in handle_ai_response(data):
                yield f"data: {json.dumps(event)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")
