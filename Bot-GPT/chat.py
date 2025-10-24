import json
import re
import time
import requests
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from extensions import db, socketio
from models import Conversation, ConversationParticipant, User
from tools import call_ollama_chat_stream, handle_tool_call
from prompts import PERSONAS, DEFAULT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT

chat = Blueprint('chat', __name__)

AGENT_SESSIONS = {}

def handle_ai_response(data):
    """Handles the AI response loop and yields events."""
    messages_str = data.get('messages', '[]')
    model = data.get('model')
    conversation_id_arg = data.get('conversation_id')
    canvas_mode = data.get('canvas_mode', False)
    agent_mode = data.get('agent_mode', False)

    try:
        messages = json.loads(messages_str)
    except json.JSONDecodeError:
        yield {"type": "agent_error", "error": "Invalid 'messages' format"}
        return

    if not model:
        model = current_user.selected_model

    persona_key = current_user.selected_persona or 'default'
    system_prompt = PERSONAS.get(persona_key, {}).get('prompt', DEFAULT_SYSTEM_PROMPT)
    if agent_mode:
        system_prompt = AGENT_SYSTEM_PROMPT

    user_id = current_user.id

    if not messages:
        yield {"type": "agent_error", "error": "No messages provided"}
        return

    conversation_id = conversation_id_arg or str(int(time.time() * 1000))

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        new_convo = Conversation(id=conversation_id, title="New Chat", owner_id=user_id)
        db.session.add(new_convo)
        owner_participant = ConversationParticipant(user_id=user_id, conversation_id=conversation_id, role='owner')
        db.session.add(owner_participant)
        db.session.commit()
        conversation = new_convo

        convo_path = os.path.join(current_app.config['USER_DATA_DIR'], str(user_id), 'conversations', f"{conversation_id}.json")
        os.makedirs(os.path.dirname(convo_path), exist_ok=True)
        with open(convo_path, 'w', encoding='utf-8') as f:
            json.dump({"messages": messages, "title": "New Chat"}, f, indent=2)

    yield {"type": "conversation_id", "id": conversation_id}

    AGENT_SESSIONS[conversation_id] = {"stop_requested": False}
    final_answer_provided = False
    file_creation_tool_used = False
    max_iterations = 100 if agent_mode else 15

    try:
        for i in range(max_iterations):
            if AGENT_SESSIONS.get(conversation_id, {}).get("stop_requested"):
                yield {"type": "agent_error", "error": "Agent run stopped by user."}
                break

            full_response_content = ""
            assistant_message = {"role": "assistant", "content": ""}

            stream = call_ollama_chat_stream(model, messages, system_prompt)
            for line in stream:
                try:
                    parsed_data = json.loads(line)
                    chunk = parsed_data.get("message", {}).get("content", "")
                    full_response_content += chunk
                    yield {"type": "assistant_chunk", "content": chunk}
                except json.JSONDecodeError:
                    continue

            assistant_message['content'] = full_response_content
            messages.append(assistant_message)
            yield {"type": "assistant_end"}

            tool_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', full_response_content)
            if not tool_match:
                final_answer_provided = True
                break

            try:
                tool_call = json.loads(tool_match.group(1))
                tool_result, file_created = handle_tool_call(tool_call, conversation, current_user)
                if file_created:
                    file_creation_tool_used = True

                if isinstance(tool_result, dict):
                    status = tool_result.get('status')
                    if status == 'canvas_created':
                        yield {"type": "open_canvas", "filename": tool_result.get('filename')}
                    elif status == 'file_written':
                        yield {"type": "file_updated", "path": tool_result.get('path'), "content": tool_result.get('content')}
                    elif status == 'plan_step_update':
                        yield {"type": "plan_step_update", "step_number": tool_result.get('step_number'), "step_description": tool_result.get('step_description')}
                        continue

                tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result}\n---"
                messages.append({"role": "user", "content": tool_response_message})
                yield {"type": "tool_result", "result": tool_result}
            except Exception as e:
                error_message = f"Error processing tool: {e}"
                messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})
                yield {"type": "tool_error", "error": error_message}
    finally:
        if conversation_id in AGENT_SESSIONS:
            del AGENT_SESSIONS[conversation_id]

    if final_answer_provided:
        # Final answer processing and canvas saving logic here...
        pass

    # Conversation title generation and saving logic here...
    pass

@socketio.on('chat_message')
@login_required
def handle_chat_message(data):
    """Handles a chat message received over WebSocket."""
    room = data.get('conversation_id') or request.sid
    messages = json.loads(data['messages'])
    emit('ai_response', {"type": "user_message", "content": messages[-1]['content']}, room=room, include_self=False)
    for event in handle_ai_response(data):
        emit('ai_response', event, room=room)

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
