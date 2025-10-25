import json
import os
import re
import time
import requests
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from extensions import db, socketio
from models import Conversation, ConversationParticipant
from tools import call_ollama_chat_stream, handle_tool_call
from prompts import PERSONAS, DEFAULT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT

chat = Blueprint('chat', __name__)

AGENT_SESSIONS = {}

def initialize_chat(data):
    """Initializes a chat session, loading messages and settings."""
    try:
        messages_str = data.get('messages', '[]')
        messages = json.loads(messages_str)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Invalid 'messages' format")

    model = data.get('model') or current_user.selected_model
    persona_key = current_user.selected_persona or 'default'
    system_prompt = PERSONAS.get(persona_key, {}).get('prompt', DEFAULT_SYSTEM_PROMPT)
    if data.get('agent_mode', False):
        system_prompt = AGENT_SYSTEM_PROMPT

    conversation_id = data.get('conversation_id') or str(int(time.time() * 1000))
    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        conversation = Conversation(id=conversation_id, title="New Chat", owner_id=current_user.id)
        db.session.add(conversation)
        participant = ConversationParticipant(user_id=current_user.id, conversation_id=conversation_id, role='owner')
        db.session.add(participant)
        db.session.commit()

    return messages, model, system_prompt, conversation

def handle_ai_response(data):
    """Handles the AI response loop and yields events."""
    try:
        messages, model, system_prompt, conversation = initialize_chat(data)
    except json.JSONDecodeError:
        yield {"type": "agent_error", "error": "Invalid 'messages' format"}
        return

    yield {"type": "conversation_id", "id": conversation.id}

    agent_mode = data.get('agent_mode', False)
    AGENT_SESSIONS[conversation.id] = {"stop_requested": False}
    max_iterations = 100 if agent_mode else 15

    tool_match = None

    try:
        for i in range(max_iterations):
            if AGENT_SESSIONS.get(conversation.id, {}).get("stop_requested"):
                yield {"type": "agent_error", "error": "Agent run stopped by user."}
                break

            full_response_content, assistant_message = "", {"role": "assistant", "content": ""}
            try:
                stream = call_ollama_chat_stream(model, messages, system_prompt)
                for chunk in stream:
                    full_response_content += chunk
                    yield {"type": "assistant_chunk", "content": chunk}
            except requests.exceptions.ConnectionError as e:
                yield {"type": "agent_error", "error": f"Could not connect to Ollama: {e}"}
                break

            assistant_message['content'] = full_response_content
            messages.append(assistant_message)
            yield {"type": "assistant_end"}

            tool_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', full_response_content)
            if not tool_match:
                break

            try:
                tool_call = json.loads(tool_match.group(1))
                tool_result, _ = handle_tool_call(tool_call, conversation, current_user)

                if isinstance(tool_result, dict):
                    status = tool_result.get('status')
                    if status == 'canvas_created':
                        yield {"type": "open_canvas", "filename": tool_result.get('filename')}
                    elif status == 'file_written':
                        yield {"type": "file_updated", "path": tool_result.get('path'), "content": tool_result.get('content')}

                tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result}\n---"
                messages.append({"role": "user", "content": tool_response_message})
                yield {"type": "tool_result", "result": tool_result}
            except Exception as e:
                error_message = f"Error processing tool: {e}"
                messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})
                yield {"type": "tool_error", "error": error_message}
    finally:
        if conversation.id in AGENT_SESSIONS:
            del AGENT_SESSIONS[conversation.id]

    if not tool_match:
        yield from process_final_answer(messages, conversation, data.get('canvas_mode', False))

    update_conversation_title(conversation, messages)
    save_conversation_history(conversation, messages)
    yield {"type": "done", "title": conversation.title}

@socketio.on('chat_message')
@login_required
def handle_chat_message(data):
    """Handles a chat message received over WebSocket."""
    room = data.get('conversation_id') or request.sid
    messages = json.loads(data['messages'])
    emit('ai_response', {"type": "user_message", "content": messages[-1]['content']}, room=room, include_self=False)
    for event in handle_ai_response(data):
        emit('ai_response', event, room=room)


@socketio.on('join')
@login_required
def handle_join_room(data):
    """Adds the current user to a Socket.IO room for conversation updates."""
    room = data.get('room')
    if room:
        join_room(room)


@socketio.on('leave')
@login_required
def handle_leave_room(data):
    """Removes the current user from a Socket.IO room when they leave a chat."""
    room = data.get('room')
    if room:
        leave_room(room)

def process_final_answer(messages, conversation, canvas_mode):
    """Processes the final answer from the AI, saving to canvas if needed."""
    final_answer_content = messages[-1]['content']
    if canvas_mode:
        code_block_match = re.search(r'```(\w*)\n([\s\S]+?)```', final_answer_content)
        if code_block_match:
            language = code_block_match.group(1).lower()
            content_to_save = code_block_match.group(2).strip()
            file_extension = {'python': 'py', 'javascript': 'js', 'html': 'html', 'css': 'css', 'json': 'json', 'sql': 'sql', 'shell': 'sh', 'bash': 'sh'}.get(language, 'txt')
        else:
            content_to_save = re.sub(r'<think>[\s\S]*?<\/think>', '', final_answer_content).strip()
            file_extension = 'md'

        timestamp = int(time.time())
        filename = f"canvas_{timestamp}.{file_extension}"

        from tools import write_file
        write_result = write_file(path=filename, content=content_to_save, conversation_id=conversation.id, user_id=conversation.owner_id)

        if "successfully" in write_result.get('message', ''):
            yield {"type": "open_canvas", "filename": filename}
            yield {"type": "refresh_files"}
        else:
            yield {"type": "agent_error", "error": f"Failed to save to canvas: {write_result.get('message', '')}"}

    yield {"type": "final_answer", "content": final_answer_content}

def update_conversation_title(conversation, messages):
    """Updates the conversation title if it's a new chat."""
    if conversation.title == "New Chat" and len(messages) >= 2:
        try:
            final_ai_message = next((m['content'] for m in reversed(messages) if m['role'] == 'assistant'), "")
            cleaned_content = re.sub(r'<think>[\s\S]*?</think>', '', final_ai_message).strip()
            title_prompt = f"Based on the following exchange, create a very short, concise title (5 words or less).\n\nUser: {messages[0]['content']}\nAssistant: {cleaned_content}\n\nTitle:"
            title_model = "llama3.2:latest"
            response = requests.post(f"{current_app.config['OLLAMA_HOST']}/api/chat", json={"model": title_model, "messages": [{"role": "user", "content": title_prompt}], "stream": False}, timeout=180)
            response.raise_for_status()
            raw_title = response.json().get("message", {}).get("content", "").strip()
            cleaned_title = re.sub(r'<think>[\s\S]*?</think>', '', raw_title).strip().replace('"', '')
            if cleaned_title:
                conversation.title = cleaned_title
        except requests.exceptions.RequestException as e:
            print(f"Could not auto-generate title: {e}")


def save_conversation_history(conversation, messages):
    """Saves the conversation history to a JSON file."""
    db.session.commit()
    conversation_path = os.path.join(current_app.config['USER_DATA_DIR'], str(conversation.owner_id), 'conversations', f"{conversation.id}.json")
    os.makedirs(os.path.dirname(conversation_path), exist_ok=True)
    with open(conversation_path, 'w', encoding='utf-8') as f:
        json.dump({"messages": messages, "title": conversation.title}, f, indent=2)

@socketio.on('stop_agent')
@login_required
def handle_stop_agent(data):
    """Handles a request to stop a running agent."""
    conversation_id = data.get('conversation_id')
    if conversation_id and conversation_id in AGENT_SESSIONS:
        AGENT_SESSIONS[conversation_id]["stop_requested"] = True
        emit('ai_response', {"type": "agent_error", "error": "Stop signal received. Attempting to halt..."})

@chat.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    persona_names = {key: value["name"] for key, value in PERSONAS.items()}
    return jsonify({
        "model": current_user.selected_model,
        "persona": current_user.selected_persona,
        "available_personas": persona_names
    })

@chat.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    data = request.get_json()
    current_user.selected_model = data.get('model')
    current_user.selected_persona = data.get('persona')
    db.session.commit()
    return jsonify({"message": "Settings updated successfully"}), 200

@chat.route('/api/models')
@login_required
def get_models():
    """Fetches the available models from the Ollama host."""
    try:
        ollama_host = current_app.config['OLLAMA_HOST']
        response = requests.get(f"{ollama_host}/api/tags")
        response.raise_for_status()
        return jsonify(response.json().get('models', []))
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502

@chat.route('/api/chat')
@login_required
def chat_proxy():
    """ (DEPRECATED) Orchestrates the ReAct loop for conversational AI."""
    messages_str = request.args.get('messages', '[]')
    model = request.args.get('model')
    conversation_id_arg = request.args.get('conversation_id')

    data = {
        "messages": messages_str,
        "model": model,
        "conversation_id": conversation_id_arg
    }

    def event_stream():
        with current_app.app_context():
            for event in handle_ai_response(data):
                yield f"data: {json.dumps(event)}\n\n"

    return Response(event_stream(), mimetype='text/event-stream')
