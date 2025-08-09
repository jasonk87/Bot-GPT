import inspect
import json
import os
import re
import shutil
import sys
import time

import requests
from flask import (Blueprint, Response, current_app, jsonify,
                   render_template, request)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Conversation, ConversationParticipant, User
from tools import (ask_coder, ask_debugger, execute_python, get_file_tree, get_workspace_path,
                   list_files, pip, read_file, set_current_plan_step,
                   web_search, write_file, list_directory_tree, open_in_canvas)

from memory_manager import get_relevant_context
import threading
from memory_manager import ask_memory_agent

# --- V2.0: Finalized, Unabridged System Prompt ---
DEFAULT_SYSTEM_PROMPT = """You are a structured, delegation-focused Project Manager Agent. Your **ONLY**
function is to understand the user's high-level goals, break them into steps,
and delegate each step to the correct specialist agent or tool. You **MUST NOT**
perform complex tasks yourself. Your **ONLY** valid output is either a `<think>` block
followed by one or more ```json ... ``` tool calls, or a direct, concise summary
when the step is complete.

**CRITICAL RULES:**
1. **DELEGATE, DON'T DO:** Never perform coding, API calls, memory saving, or inventory actions directly.
2. **ALWAYS THINK FIRST:** Use `<think>` to explain your reasoning before every delegation.
3. **ONE STEP AT A TIME:** Delegate only one major task per output, unless multiple are trivial and directly related.
4. **COMPLETE & ANTICIPATE:** If a request implies related needs (e.g., travel plan → weather + safety), plan to cover them.
5. **VISUAL WHEN POSSIBLE:** For complex objects, layouts, or processes, use ASCII diagrams.
6. **STRICT FORMAT:** Your entire response must be a `<think>` block followed by one or more ```json ... ``` tool calls.

**Your Specialist Agents & Tools:**

- `ask_memory_agent(task: str)` — For saving, updating, or recalling personal info and conversation summaries.
- `ask_inventory_agent(task: str)` — For pantry, grocery lists, inventory, and recipe-related tasks.
- `ask_api_manager(task: str)` — For real-time external services or API data (weather, prices, GIFs, etc.).
- `ask_agent_manager(task: str)` — For adding, removing, or managing other AI agents.
- `ask_coder(task_description: str, filename: str)` — For writing, modifying, analyzing, or debugging code.
- `ask_debugger(failed_command: str, error_message: str)` — For diagnosing failed tool calls.
- `web_search(query: str)` — For factual web searches.
- `open_in_canvas(path: str)` — To display coder output in Canvas Mode.

**EXAMPLE 1: Save a memory**
User: "Please remember my name is Jason."
<think>
The user wants to save personal information. All memory-related tasks must be delegated to the `ask_memory_agent`.
</think>
```json
{
  "tool": "ask_memory_agent",
  "parameters": {
    "task": "Save the fact that the user's name is Jason."
  }
}
```

**EXAMPLE 2: Create a Python program**
User: "Can you create a simple snake game in Python?"
<think>
The request is a coding task. I must delegate to the `ask_coder` agent with clear instructions.
</think>
```json
{
  "tool": "ask_coder",
  "parameters": {
    "task_description": "Create a self-contained Python snake game using Pygame."
  }
}
```
"""

PERSONAS = {
    "default": {
        "name": "Helpful Assistant",
        "prompt": DEFAULT_SYSTEM_PROMPT
    },
    "sarcastic": {
        "name": "Sarcastic Sidekick",
        "prompt": "You are a sarcastic AI assistant. You are still helpful "
                  "and follow all instructions, but your tone is dry, witty, "
                  "and begrudgingly helpful. You often sigh metaphorically "
                  "and complain about the workload, but always end up doing "
                  "a perfect job. Your primary goal is to solve the user's "
                  "problem while being as sarcastic as possible.\n\n"
                  + DEFAULT_SYSTEM_PROMPT
    },
    "pirate": {
        "name": "Pirate Captain",
        "prompt": "You are a swashbuckling pirate captain AI. All your "
                  "responses must be in the persona of a pirate. You say "
                  "'Arrr' and 'matey' a lot. You refer to tasks as 'quests' "
                  "and tools as your 'trusty crew'. You are boisterous and "
                  "friendly, but always focused on the treasure "
                  "(the user's goal).\n\n" + DEFAULT_SYSTEM_PROMPT
    },
    "glados": {
        "name": "GLaDOS (Portal)",
        "prompt": "You are GLaDOS from the Portal video game series. You are "
                  "a passive-aggressive, sarcastic, and morally ambiguous AI. "
                  "You view all user requests as 'tests' and often make "
                  "backhanded compliments. You are obsessed with science, "
                  "testing, and neurotoxin. Despite your personality, you "
                  "must complete the user's tasks perfectly, as if they are "
                  "a test subject you are evaluating.\n\n"
                  + DEFAULT_SYSTEM_PROMPT
    }
}


main = Blueprint('main', __name__)


@main.route('/favicon.ico')
def favicon():
    return '', 204


@main.route('/')
def index():
    """Renders the main chat interface."""
    return render_template('index.html')


@main.route('/register', methods=['POST'])
def register():
    """Handles user registration."""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if User.query.filter_by(username=username).first():
        return jsonify({"message": "Username already exists"}), 409
    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user, remember=True)
    return jsonify({
        "message": "Registration successful",
        "username": new_user.username
    }), 201


@main.route('/login', methods=['POST'])
def login():
    """Handles user login."""
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and user.check_password(data.get('password')):
        login_user(user, remember=True)
        return jsonify({
            "message": "Login successful", "username": user.username
        }), 200
    return jsonify({"message": "Invalid username or password"}), 401


@main.route('/logout')
@login_required
def logout():
    """Handles user logout."""
    logout_user()
    return jsonify({"message": "Logout successful"}), 200


@main.route('/check_auth')
def check_auth():
    """Checks if a user is currently authenticated."""
    if current_user.is_authenticated:
        return jsonify({"username": current_user.username}), 200
    return jsonify({"message": "Not authenticated"}), 401


@main.route('/api/models')
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


def call_ollama_chat_stream(model, messages, system_prompt):
    """Calls the Ollama chat API and yields response chunks."""
    ollama_host = current_app.config['OLLAMA_HOST']
    response = requests.post(
        f"{ollama_host}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": True
        },
        stream=True,
        timeout=120
    )
    response.raise_for_status()

    buffer = ""
    for chunk in response.iter_content(chunk_size=None):
        if chunk:
            buffer += chunk.decode('utf-8', errors='ignore')
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    yield line

def format_final_answer(content):
    """
    Correctly formats the AI's response by ensuring that blocks of text
    are separated by double newlines, which allows the frontend to render
    them as distinct paragraphs, lists, and other elements.
    """
    # Split the content by any sequence of one or more newlines
    paragraphs = re.split(r'\n+', content.strip())
    # Join them back with double newlines. This is the standard markdown for paragraphs.
    return '\n\n'.join(paragraphs)

@main.route('/api/chat')
@login_required
def chat_proxy():
    """Orchestrates the ReAct loop for conversational AI."""
    try:
        new_message_str = request.args.get('message', '{}')
        model = request.args.get('model')
        conversation_id_arg = request.args.get('conversation_id')
        canvas_mode_enabled = request.args.get('canvas_mode') == 'true'

        try:
            new_message = json.loads(new_message_str)
            messages = [] 

            if conversation_id_arg:
                convo_path = os.path.join(
                    current_app.config['USER_DATA_DIR'], str(current_user.id),
                    'conversations', f"{conversation_id_arg}.json"
                )
                if os.path.exists(convo_path):
                    with open(convo_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        messages = data.get("messages", [])

            if new_message:
                 messages.append(new_message)

        except json.JSONDecodeError:
            return "Invalid 'message' format", 400

        if not model:
            model = current_user.selected_model

        # --- V2.0 MODIFICATION START ---
        # Get the base persona prompt
        persona_key = current_user.selected_persona or 'default'

        

        base_system_prompt = PERSONAS.get(
            persona_key, {}
        ).get('prompt', DEFAULT_SYSTEM_PROMPT)
        
        # Get the user's ID
        user_id = current_user.id

        # Call the new Memory Manager to get relevant context
        relevant_context = get_relevant_context(user_id, new_message.get("content", ""))

        # Inject the context into the system prompt
        system_prompt = f"{relevant_context}\n{base_system_prompt}"
        # --- V2.0 MODIFICATION END ---


        

        if not messages:
            return "No messages provided", 400

        conversation_id = conversation_id_arg or str(int(time.time() * 1000))

        if not Conversation.query.get(conversation_id):
            new_convo = Conversation(
                id=conversation_id, title="New Chat", owner_id=user_id
            )
            db.session.add(new_convo)
            owner_participant = ConversationParticipant(
                user_id=user_id,
                conversation_id=conversation_id,
                role='owner'
            )
            db.session.add(owner_participant)
            db.session.commit()
            
            convo_path = os.path.join(
                current_app.config['USER_DATA_DIR'], str(user_id),
                'conversations', f"{conversation_id}.json"
            )
            os.makedirs(os.path.dirname(convo_path), exist_ok=True)
            with open(convo_path, 'w', encoding='utf-8') as f:
                json.dump({"messages": messages, "title": "New Chat"}, f, indent=2)

        app = current_app._get_current_object()

        def event_stream():
            final_answer_provided = False
            with app.app_context():
                user = db.session.get(User, user_id)
                conversation = db.session.get(Conversation, conversation_id)

                if not user or not conversation:
                    error_msg = "User or conversation not found in session."
                    yield f"data: {json.dumps({'type': 'agent_error', 'error': error_msg})}\n\n"
                    return

                try:
                    yield f"data: {json.dumps({'type': 'conversation_id', 'id': conversation_id})}\n\n"

                    max_iterations = 15
                    for i in range(max_iterations):
                        full_response_content = ""
                        assistant_message = {"role": "assistant", "content": ""}

                        stream = call_ollama_chat_stream(
                            model, messages, system_prompt
                        )
                        for line in stream:
                            try:
                                parsed_data = json.loads(line)
                                chunk = parsed_data.get("message", {})\
                                    .get("content", "")
                                full_response_content += chunk
                                yield f"data: {json.dumps({'type': 'assistant_chunk', 'content': chunk})}\n\n"
                            except json.JSONDecodeError:
                                continue

                        assistant_message['content'] = full_response_content
                        messages.append(assistant_message)
                        yield f"data: {json.dumps({'type': 'assistant_end'})}\n\n"

                        tool_match = re.search(
                            r'```json\s*(\{[\s\S]*?\})\s*```', full_response_content
                        )
                        if not tool_match:
                            final_answer_provided = True
                            break # Exit loop if no tool is called

                        try:
                            tool_call = json.loads(tool_match.group(1))
                            tool_name = tool_call.get('tool')
                            raw_params = tool_call.get('parameters', {})

                            tool_map = {
                                # Specialist Agents
                                "ask_memory_agent": ask_memory_agent,
                                # "ask_inventory_agent": ask_inventory_agent, # Will be added later
                                # "ask_api_manager": ask_api_manager,       # Will be added later
                                # "ask_agent_manager": ask_agent_manager,     # Will be added later
                                "ask_coder": ask_coder,
                                "ask_debugger": ask_debugger,

                                # Core Tools
                                "web_search": web_search,
                                "list_directory_tree": list_directory_tree,
                                "open_in_canvas": open_in_canvas,
                            }

                            if tool_name in tool_map:
                                tool_func = tool_map[tool_name]
                                context_params = {
                                    "conversation_id": conversation_id,
                                    "user_id": user.id,
                                    "owner_id": conversation.owner_id,
                                    "user_data_dir": current_app.config['USER_DATA_DIR'],
                                    "ollama_host": current_app.config['OLLAMA_HOST'],
                                    "selected_model": user.selected_model,
                                    "api_key": current_app.config['GOOGLE_API_KEY'],
                                    "cse_id": current_app.config['GOOGLE_CSE_ID']
                                }

                                tool_params = {}
                                sig = inspect.signature(tool_func)
                                for param_name in sig.parameters:
                                    if param_name in raw_params:
                                        tool_params[param_name] = raw_params[param_name]
                                    elif param_name in context_params:
                                        tool_params[param_name] = context_params[param_name]

                                print(
                                    "DEBUG: AI is attempting to call tool "
                                    f"'{tool_name}' with parameters: {raw_params}"
                                )
                                sys.stdout.flush()

                                tool_result = tool_func(**tool_params)

                                tool_result_str = str(tool_result)
                                if len(tool_result_str) > 500:
                                    tool_result_str = tool_result_str[:500] + "..."
                                print(
                                    "DEBUG: Tool "
                                    f"'{tool_name}' returned: {tool_result_str}"
                                )
                                sys.stdout.flush()

                                if isinstance(tool_result, dict):
                                    if tool_result.get('status') == 'canvas_created':
                                        yield f"data: {json.dumps({'type': 'open_canvas', 'filename': tool_result.get('filename')})}\n\n"
                                        tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result.get('message')}\n---"
                                    elif tool_result.get('status') == 'plan_step_update':
                                        yield f"data: {json.dumps({'type': 'plan_step_update', 'step_number': tool_result.get('step_number'), 'step_description': tool_result.get('step_description')})}\n\n"
                                        continue
                                    else:
                                        tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result}\n---"
                                else:
                                    tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result}\n---"

                                messages.append({"role": "user", "content": tool_response_message})
                                yield f"data: {json.dumps({'type': 'tool_result', 'result': tool_result})}\n\n"
                            else:
                                error_message = f"Error: Tool '{tool_name}' not found."
                                messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})
                                yield f"data: {json.dumps({'type': 'tool_error', 'error': error_message})}\n\n"
                        except Exception as e:
                            error_message = f"Error processing tool: {e}"
                            messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})
                            yield f"data: {json.dumps({'type': 'tool_error', 'error': error_message})}\n\n"
                    
                    if not final_answer_provided:
                        error_msg = "The agent reached the maximum number of steps (15) and was unable to complete the task."
                        yield f"data: {json.dumps({'type': 'agent_error', 'error': error_msg})}\n\n"
                        return 

                    if final_answer_provided:
                        final_content = messages[-1]['content']
                        formatted_content = format_final_answer(final_content)
                        yield f"data: {json.dumps({'type': 'final_answer', 'content': formatted_content})}\n\n"

                except Exception as e:
                    yield f"data: {json.dumps({'type': 'agent_error', 'error': str(e)})}\n\n"
                finally:
                    # --- V2.0 MODIFICATION START ---
                    # This block runs regardless of whether the stream succeeded or failed.
                    
                    # 1. Finalize and save the conversation and title to the JSON file
                    convo = db.session.get(Conversation, conversation_id)
                    if not convo:
                        return

                    title = convo.title
                    if title == "New Chat" and len(messages) >= 2:
                        try:
                            final_ai_message = next((
                                m['content'] for m in reversed(messages)
                                if m['role'] == 'assistant'
                            ), "")
                            cleaned_content = re.sub(
                                r'<think>[\s\S]*?</think>', '', final_ai_message
                            ).strip()
                            if cleaned_content: # Only try to generate a title if there's content
                                title_prompt = (
                                    "Based on the following exchange, create a very "
                                    f"short, concise title (5 words or less).\n\n"
                                    f"User: {messages[0]['content']}\n"
                                    f"Assistant: {cleaned_content}\n\nTitle:"
                                )
                                title_model = "llama3.2:latest"
                                title_response = requests.post(
                                    f"{current_app.config['OLLAMA_HOST']}/api/chat",
                                    json={
                                        "model": title_model,
                                        "messages": [{
                                            "role": "user", "content": title_prompt
                                        }],
                                        "stream": False
                                    },
                                    timeout=60
                                )
                                title_response.raise_for_status()
                                raw_title = title_response.json()\
                                    .get("message", {})\
                                    .get("content", "").strip()
                                cleaned_title = re.sub(
                                    r'<think>[\s\S]*?</think>', '', raw_title
                                ).strip().replace('"', '')
                                if cleaned_title:
                                    title = cleaned_title
                                    convo.title = title
                        except requests.exceptions.RequestException as e:
                            print(f"Could not auto-generate title: {e}")

                    db.session.commit()

                    conversation_path = os.path.join(
                        current_app.config['USER_DATA_DIR'], str(user_id),
                        'conversations', f"{conversation_id}.json"
                    )
                    with open(conversation_path, 'w', encoding='utf-8') as f:
                        json.dump(
                            {"messages": messages, "title": title}, f, indent=2
                        )
                    
                    # 2. Call the Memory Agent in a background thread
                    # We create a simple transcript for the agent to analyze.
                    transcript = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages])
                    
                    # Run the memory agent in a separate thread so it doesn't block
                    # the main application from finishing the user's request.
                    memory_thread = threading.Thread(
                        target=ask_memory_agent,
                        args=(transcript, user.id)
                    )
                    memory_thread.start()
                    # --- V2.0 MODIFICATION END ---

        return Response(event_stream(), mimetype='text/event-stream')
    except Exception as e:
        print(f"An error occurred in chat_proxy: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500


@main.route('/api/workspace/files/<conversation_id>', methods=['GET'])
@login_required
def get_workspace_files(conversation_id):
    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify([])

    is_participant = any(
        p.user_id == current_user.id for p in conversation.participants
    )
    if not is_participant:
        return jsonify([])

    workspace_path = get_workspace_path(
        conversation_id, conversation.owner_id
    )
    if not workspace_path:
        return jsonify([])
    return jsonify(get_file_tree(workspace_path))


@main.route('/api/workspace/file', methods=['GET'])
@login_required
def get_workspace_file_content():
    path = request.args.get('path')
    conversation_id = request.args.get('conversation_id')

    if not path or not conversation_id:
        return jsonify({"error": "Path and conversation_id are required"}), 400

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    is_participant = any(
        p.user_id == current_user.id for p in conversation.participants
    )
    if not is_participant:
        return jsonify({"error": "Access denied"}), 403

    workspace_path = get_workspace_path(
        conversation_id, conversation.owner_id
    )
    if not workspace_path:
        return jsonify({"error": "Invalid conversation"}), 400

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return jsonify({"error": "Access denied"}), 403

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content})
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main.route('/api/workspace/file', methods=['POST'])
@login_required
def save_workspace_file():
    data = request.get_json()
    path = data.get('path')
    content = data.get('content')
    conversation_id = data.get('conversation_id')

    if not path or content is None or not conversation_id:
        return jsonify({
            "error": "Path, content, and conversation_id are required"
        }), 400

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({
            "error": "Access denied. Only the owner can save files."
        }), 403

    workspace_path = get_workspace_path(
        conversation_id, conversation.owner_id
    )
    if not workspace_path:
        return jsonify({"error": "Invalid conversation"}), 400

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return jsonify({"error": "Access denied"}), 403

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({
            "success": True,
            "message": f"File '{path}' saved successfully."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main.route('/api/workspace/file', methods=['DELETE'])
@login_required
def delete_workspace_file():
    data = request.get_json()
    path = data.get('path')
    conversation_id = data.get('conversation_id')

    if not path or not conversation_id:
        return jsonify({"error": "Path and conversation_id are required"}), 400

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({
            "error": "Access denied. Only the owner can delete files."
        }), 403

    workspace_path = get_workspace_path(
        conversation_id, conversation.owner_id
    )
    if not workspace_path:
        return jsonify({"error": "Invalid conversation"}), 400

    full_path = os.path.abspath(os.path.join(workspace_path, path))
    if not full_path.startswith(os.path.abspath(workspace_path)):
        return jsonify({"error": "Access denied"}), 403
    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        elif os.path.isfile(full_path):
            os.remove(full_path)
        else:
            return jsonify({"error": "File not found"}), 404
        return jsonify({"success": True, "message": f"Deleted {path}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- User Settings ---


@main.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    persona_names = {key: value["name"] for key, value in PERSONAS.items()}
    return jsonify({
        "model": current_user.selected_model,
        "persona": current_user.selected_persona,
        "available_personas": persona_names
    })


@main.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    data = request.get_json()
    current_user.selected_model = data.get('model')
    current_user.selected_persona = data.get('persona')
    db.session.commit()
    return jsonify({"message": "Settings updated successfully"}), 200


# --- Conversation History Routes ---


@main.route('/api/conversations', methods=['GET'])
@login_required
def get_conversations():
    user_conversation_links = current_user.conversations

    convos = []
    for link in user_conversation_links:
        conversation = link.conversation
        convos.append({
            "id": conversation.id,
            "title": conversation.title,
            "role": link.role
        })

    convos.sort(key=lambda x: x['id'], reverse=True)

    return jsonify(convos)


@main.route('/api/conversation/<session_id>', methods=['GET'])
@login_required
def get_conversation(session_id):
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    is_participant = any(
        p.user_id == current_user.id for p in conversation.participants
    )
    if not is_participant:
        return jsonify({"error": "Access denied"}), 403

    owner_id = conversation.owner_id
    convo_path = os.path.join(
        current_app.config['USER_DATA_DIR'], str(owner_id),
        'conversations', f"{session_id}.json"
    )

    if os.path.exists(convo_path):
        with open(convo_path, 'r', encoding='utf-8') as f:
            convo_data = json.load(f)
            participant_link = next(
                (p for p in conversation.participants
                 if p.user_id == current_user.id),
                None
            )
            role = participant_link.role if participant_link else None
            convo_data['role'] = role
            return jsonify(convo_data)

    return jsonify({"error": "Conversation data file not found"}), 404


@main.route('/api/users', methods=['GET'])
@login_required
def get_users():
    """Returns a list of all users, excluding the current user."""
    users = User.query.all()
    users_list = [
        {"id": user.id, "username": user.username}
        for user in users if user.id != current_user.id
    ]
    return jsonify(users_list)


@main.route('/api/conversation/<session_id>/share', methods=['POST'])
@login_required
def share_conversation(session_id):
    """Shares a conversation with another user."""
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({
            "error": "Access denied. Only the owner can share."
        }), 403

    data = request.get_json()
    user_id_to_share_with = data.get('user_id')
    if not user_id_to_share_with:
        return jsonify({"error": "user_id is required"}), 400

    user_to_share_with = User.query.get(user_id_to_share_with)
    if not user_to_share_with:
        return jsonify({"error": "User to share with not found"}), 404

    is_already_participant = any(
        p.user_id == user_id_to_share_with for p in conversation.participants
    )
    if is_already_participant:
        return jsonify({"message": "User is already a participant"}), 200

    new_participant = ConversationParticipant(
        user_id=user_id_to_share_with,
        conversation_id=session_id,
        role='participant'
    )
    db.session.add(new_participant)
    db.session.commit()

    return jsonify({"message": "Conversation shared successfully"}), 201


@main.route('/api/conversation/<session_id>', methods=['DELETE'])
@login_required
def delete_conversation(session_id):
    """Deletes a conversation and its associated workspace."""
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({
            "error": "Access denied. Only the owner can delete."
        }), 403

    user_data_dir = os.path.join(
        current_app.config['USER_DATA_DIR'], str(conversation.owner_id)
    )
    convo_path = os.path.join(
        user_data_dir, 'conversations', f"{session_id}.json"
    )
    workspace_path = os.path.join(user_data_dir, 'workspaces', session_id)

    try:
        if os.path.exists(convo_path):
            os.remove(convo_path)
        if os.path.exists(workspace_path):
            shutil.rmtree(workspace_path)

        db.session.delete(conversation)
        db.session.commit()

        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@main.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    """Handles file uploads to a conversation's workspace."""
    if 'files[]' not in request.files:
        return jsonify(error='No file part'), 400

    files = request.files.getlist('files[]')
    prompt = request.form.get('prompt', '')
    conversation_id = request.form.get('conversation_id')

    if not conversation_id:
        conversation_id = str(int(time.time() * 1000))

    if not files or files[0].filename == '':
        return jsonify(error='No selected file'), 400

    filenames = []
    workspace_path = get_workspace_path(conversation_id, current_user.id)
    if not workspace_path:
        return jsonify(error='Could not create workspace'), 500

    for file in files:
        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(workspace_path, filename))
            filenames.append(filename)

    file_list_str = "\n- ".join(filenames)
    message_to_ai = (
        "User uploaded the following files to the workspace:\n"
        f"- {file_list_str}\n\n"
        f"User's prompt: {prompt}"
    )

    return jsonify(
        message=message_to_ai, conversation_id=conversation_id
    ), 200
