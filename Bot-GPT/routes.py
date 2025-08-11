import json
import os
import re
import shutil
import requests
import time
import datetime

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Conversation, ConversationParticipant, User
from tools import (
    get_file_tree,
    get_workspace_path,
    web_search,
    write_file_main,
    list_directory_tree,
    open_in_canvas,
    convert_file_main,
    read_file_main,
)
from memory_manager import get_relevant_context, process_conversation_in_background
from agents import CoderAgent, DebuggerAgent

# --- V2.1: Synchronous Coder & Empowered Main Agent ---
DEFAULT_SYSTEM_PROMPT = """You are a structured, delegation-focused Project Manager Agent. Your
function is to understand the user's high-level goals, break them into steps,
and delegate each step to the correct specialist agent or tool.

**CRITICAL RULES:**
1.  **SYNCHRONOUS OPERATIONS:** All tool calls, including `ask_coder`, are now synchronous. You must wait for a tool to return before proceeding.
2.  **SELECTIVE DELEGATION:**
    *   For complex coding tasks (writing new applications, complex debugging), delegate to `ask_coder`.
    *   For simple file tasks (creating a new empty file, reading a file, converting formats), use your own tools: `write_file`, `read_file`, `convert_file`.
3.  **ALWAYS THINK FIRST:** Use `<think>` to explain your reasoning before every tool call.
4.  **STRICT OUTPUT FORMAT:** Your entire response **MUST** be a `<think>` block followed by a **single** ````json ... ```` tool call.
5.  **HANDLE CODER OUTPUT:** After `ask_coder` runs, it will return a JSON object with a summary and a list of modified files. Your next action is to `read_file` for each modified file to show the user the changes.
6.  **BE CONVERSATIONAL:** When a tool or agent finishes, summarize what was done in a friendly, conversational tone.

**Your Tools & Specialist Agents:**
- `ask_coder(task_description: str)`: For complex coding tasks. This is a synchronous call.
- `write_file(path: str, content: str)`: To create or overwrite a file.
- `read_file(path: str)`: To read a file's content.
- `convert_file(input_path: str, output_path: str)`: To convert a file's format.
- `web_search(query: str)`: For factual web searches.
- `ask_debugger(failed_command: str, error_message: str)`: For diagnosing failed tool calls.

**EXAMPLE 1: Create a simple file**
User: "Create a file named 'hello.txt' with the content 'Hello, World!'ר"
<think>
The user wants to create a simple file. This is a task I can handle directly with the `write_file` tool.
</think>
```json
{
  "tool": "write_file",
  "parameters": {
    "path": "hello.txt",
    "content": "Hello, World!"
  }
}
```

**EXAMPLE 2: A complex coding task**
User: "Create a Python web server using Flask."
<think>
This is a complex coding task. I must delegate this to the `ask_coder` agent.
</think>
```json
{
  "tool": "ask_coder",
  "parameters": {
    "task_description": "Create a simple 'Hello, World' web server using the Flask framework in a single Python file named 'app.py'."
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
                  "problem while being as sarcastic as possible.\n\n" +
                  DEFAULT_SYSTEM_PROMPT
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
                  "a test subject you are evaluating.\n\n" +
                  DEFAULT_SYSTEM_PROMPT
    }
}


main = Blueprint('main', __name__)

coder_agent = CoderAgent()
debugger_agent = DebuggerAgent()


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
        print(f"DEBUG: Received status code {response.status_code} from Ollama.")
        response.raise_for_status()
        return jsonify(response.json().get('models', []))
    except requests.exceptions.RequestException as e:
        print(f"CRITICAL ERROR in get_models: {e}")
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
    are separated by double newlines, while preserving the single newlines
    inside code blocks (```).
    """
    parts = re.split(r'(```[\s\S]*?```)', content)
    for i in range(len(parts)):
        if i % 2 == 1:
            continue
        else:
            parts[i] = re.sub(r'\n{2,}', '\n\n', parts[i]).strip()
    return '\n\n'.join(p for p in parts if p)


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

        user_id = current_user.id
        user_message = new_message.get('content', '')
        rag_context = get_relevant_context(user_id, user_message)

        persona_key = current_user.selected_persona or 'default'
        base_system_prompt = PERSONAS.get(
            persona_key, {}
        ).get('prompt', DEFAULT_SYSTEM_PROMPT)
        current_time_str = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        time_context = "CONTEXT: The current date and time is {}.".format(current_time_str)
        ui_context = "CONTEXT: Canvas Mode is currently {}.".format('ON' if canvas_mode_enabled else 'OFF')
        system_prompt = "{}\n\n{}\n\n{}\n{}".format(rag_context, ui_context, time_context, base_system_prompt)

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
                    yield "data: {}\n\n".format(json.dumps({'type': 'agent_error', 'error': error_msg}))
                    return

                try:
                    yield "data: {}\n\n".format(json.dumps({'type': 'conversation_id', 'id': conversation_id}))
                    max_iterations = 15
                    for i in range(max_iterations):
                        full_response_content = ""
                        assistant_message = {"role": "assistant", "content": ""}

                        stream = call_ollama_chat_stream(model, messages, system_prompt)
                        for line in stream:
                            try:
                                parsed_data = json.loads(line)
                                chunk = parsed_data.get("message", {}).get("content", "")
                                full_response_content += chunk
                                yield "data: {}\n\n".format(json.dumps({'type': 'assistant_chunk', 'content': chunk}))
                            except json.JSONDecodeError:
                                continue

                        assistant_message['content'] = full_response_content
                        messages.append(assistant_message)
                        yield "data: {}\n\n".format(json.dumps({'type': 'assistant_end'}))

                        print("\n" + "=" * 80)
                        print(">>> MAIN AGENT RAW RESPONSE (Turn {}) <<<".format(i + 1))
                        print("-" * 80)
                        print(full_response_content)
                        print("=" * 80 + "\n")

                        tool_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', full_response_content)
                        if not tool_match:
                            final_answer_provided = True
                            break

                        try:
                            tool_call = json.loads(tool_match.group(1))
                            tool_name = tool_call.get('tool')
                            raw_params = tool_call.get('parameters', {})

                            print("\n[DEBUG] AGENT REQUESTING TOOL CALL")
                            print("  - Tool: {}".format(tool_name))
                            print("  - Parameters: {}".format(json.dumps(raw_params, indent=2)))

                            tool_map = {
                                "ask_coder": coder_agent.execute,
                                "ask_debugger": debugger_agent.execute,
                                "web_search": web_search,
                                "list_directory_tree": list_directory_tree,
                                "open_in_canvas": open_in_canvas,
                                "read_file": read_file_main,
                                "write_file": write_file_main,
                                "convert_file": convert_file_main,
                            }

                            if tool_name in tool_map:
                                tool_func = tool_map[tool_name]
                                tool_response_message = ""
                                yield "data: {}\n\n".format(json.dumps({'type': 'tool_call', 'name': tool_name, 'params': raw_params}))
                                if tool_name == "ask_coder":
                                    workspace_path = get_workspace_path(conversation.id, conversation.owner_id)
                                    coder_event_generator = coder_agent.execute(
                                        task_description=raw_params.get("task_description", ""),
                                        workspace_path=workspace_path
                                    )
                                    tool_result = None
                                    for event in coder_event_generator:
                                        event['type'] = "coder_{}".format(event['type'])
                                        yield "data: {}\n\n".format(json.dumps(event))
                                        if event['type'] == 'coder_final_result':
                                            tool_result = event
                                else:
                                    tool_result = tool_func(**raw_params)

                                print("\n[DEBUG] TOOL EXECUTION RESULT")
                                print("  - Tool: {}".format(tool_name))
                                if isinstance(tool_result, dict):
                                    print("  - Result: {}".format(json.dumps(tool_result, indent=2)))
                                else:
                                    print("  - Result: {}".format(tool_result))
                                if isinstance(tool_result, dict):
                                    if tool_result.get('status') == 'canvas_created':
                                        yield "data: {}\n\n".format(json.dumps({'type': 'open_canvas', 'filename': tool_result.get('filename')}))
                                        tool_response_message = "TOOL RESPONSE:\n---\n{}\n---".format(tool_result.get('message'))
                                    elif tool_result.get('type') == 'coder_final_result':
                                        coder_response_for_pm = {
                                            "summary": tool_result.get('summary'),
                                            "modified_files": tool_result.get('modified_files', [])
                                        }
                                        tool_response_message = "TOOL RESPONSE:\n---\n{}\n---".format(json.dumps(coder_response_for_pm))
                                    elif 'modified_files' in tool_result:
                                        tool_response_message = "TOOL RESPONSE:\n---\n{}\n---".format(json.dumps(tool_result))
                                    else:
                                        tool_response_message = "TOOL RESPONSE:\n---\n{}\n---".format(json.dumps(tool_result))
                                else:
                                    tool_response_message = "TOOL RESPONSE:\n---\n{}\n---".format(str(tool_result))

                                messages.append({"role": "user", "content": tool_response_message})
                                yield "data: {}\n\n".format(json.dumps({'type': 'tool_result', 'result': tool_result}))
                            else:
                                error_message = "Error: Tool '{}' not found.".format(tool_name)
                                messages.append({"role": "user", "content": "TOOL RESPONSE: {}".format(error_message)})
                                yield "data: {}\n\n".format(json.dumps({'type': 'tool_error', 'error': error_message}))
                        except Exception as e:
                            error_message = "Error processing tool: {}".format(str(e))
                            messages.append({"role": "user", "content": "TOOL RESPONSE: {}".format(error_message)})
                            yield "data: {}\n\n".format(json.dumps({'type': 'tool_error', 'error': error_message}))
                    if not final_answer_provided and i == max_iterations - 1:
                        error_msg = "The agent reached the maximum number of steps (15) and was unable to complete the task."
                        yield "data: {}\n\n".format(json.dumps({'type': 'agent_error', 'error': error_msg}))
                        return

                    if final_answer_provided:
                        final_content = messages[-1]['content']
                        formatted_content = format_final_answer(final_content)
                        yield "data: {}\n\n".format(json.dumps({'type': 'final_answer', 'content': formatted_content}))

                except Exception as e:
                    yield "data: {}\n\n".format(json.dumps({'type': 'agent_error', 'error': str(e)}))
                finally:
                    convo = db.session.get(Conversation, conversation_id)
                    if not convo:
                        return

                    title = convo.title
                    if title == "New Chat" and len(messages) >= 2:
                        try:
                            final_ai_message = next((m['content'] for m in reversed(messages) if m['role'] == 'assistant'), "")
                            cleaned_content = re.sub(r'<think>[\s\S]*?</think>', '', final_ai_message).strip()
                            if cleaned_content:
                                title_prompt = (
                                    "Based on the following exchange, create a very short, "
                                    "concise title (5 words or less).\n\n"
                                    "User: {}\nAssistant: {}\n\nTitle:".format(messages[0]['content'], cleaned_content)
                                )
                                title_model = "llama3.2:latest"
                                title_response = requests.post(
                                    "{}/api/chat".format(current_app.config['OLLAMA_HOST']),
                                    json={
                                        "model": title_model,
                                        "messages": [{"role": "user", "content": title_prompt}],
                                        "stream": False
                                    },
                                    timeout=60
                                )
                                title_response.raise_for_status()
                                raw_title = title_response.json().get("message", {}).get("content", "").strip()
                                cleaned_title = re.sub(r'<think>[\s\S]*?</think>', '', raw_title).strip().replace('"', '')
                                if cleaned_title:
                                    title = cleaned_title
                                    convo.title = title
                        except requests.exceptions.RequestException as e:
                            print("Could not auto-generate title: {}".format(e))

                    db.session.commit()

                    conversation_path = os.path.join(
                        current_app.config['USER_DATA_DIR'], str(user_id),
                        'conversations', "{}.json".format(conversation_id)
                    )

                    final_messages_to_save = []
                    for msg in messages:
                        if msg['role'] == 'user' and not msg['content'].startswith("TOOL RESPONSE:"):
                            final_messages_to_save.append(msg)
                        elif msg['role'] == 'assistant' and '```json' not in msg['content']:
                            final_messages_to_save.append(msg)
                    with open(conversation_path, 'w', encoding='utf-8') as f:
                        json.dump({"messages": final_messages_to_save, "title": title}, f, indent=2)

                    process_conversation_in_background(conversation_id)

        return Response(event_stream(), mimetype='text/event-stream')
    except Exception as e:
        print("An error occurred in chat_proxy: {}".format(e))
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
            "message": "File '{}' saved successfully.".format(path)
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
        return jsonify({"success": True, "message": "Deleted {}".format(path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

    convos.sort(key=lambda x: x['id'], reverse=False)

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
        'conversations', "{}.json".format(session_id)
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
        user_data_dir, 'conversations', "{}.json".format(session_id)
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
        f"User uploaded the following files to the workspace:\n"
        f"- {file_list_str}\n\n"
        f"User's prompt: {prompt}"
    )

    return jsonify(
        message=message_to_ai, conversation_id=conversation_id
    ), 200


@main.route('/api/workspace/download', methods=['GET'])
@login_required
def download_workspace_file():
    """Securely serves a file from a user's workspace for download."""
    path = request.args.get('path')
    conversation_id = request.args.get('conversation_id')

    if not path or not conversation_id:
        return jsonify({"error": "Path and conversation_id are required"}), 400

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    is_participant = any(p.user_id == current_user.id for p in conversation.participants)
    if not is_participant:
        return jsonify({"error": "Access denied"}), 403

    workspace_dir = get_workspace_path(conversation_id, conversation.owner_id)
    if not workspace_dir:
        return jsonify({"error": "Invalid workspace"}), 400

    filename = os.path.basename(path)

    try:
        return send_from_directory(
            workspace_dir,
            filename,
            as_attachment=True
        )
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500