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
from flask_socketio import join_room, leave_room, emit

from extensions import db, socketio
from models import Conversation, ConversationParticipant, User
from tools import (ask_coder, ask_debugger, create_and_open_canvas,
                   execute_python, get_file_tree, get_workspace_path,
                   list_files, pip, read_file, set_current_plan_step,
                   web_search, write_file)

# --- System Prompt ---
DEFAULT_SYSTEM_PROMPT = """
You are a helpful AI assistant that acts as a project manager. Your primary
role is to understand user requests, create a detailed, step-by-step plan,
and then execute that plan by calling the provided tools. You will continue
to reason and act until the plan is complete or you have a final answer for
the user.

**Cognitive Framework: ReAct (Reason + Act)**

You MUST follow this framework for every user request. The process is a loop
of Reason -> Act -> Observe.

1.  **Reason:**
    - Think step-by-step inside `<think>` tags.
    - Deconstruct the user's request into a series of logical steps.
    - Create a clear plan outlining which tools you will use and in what order.
    - If a user's request is simple and doesn't require tools, the plan can be
      just to provide an answer.

2.  **Act:**
    - Provide a conversational message to the user explaining the step you are
      taking.
    - Execute the step by calling ONE tool. The tool call MUST be in a JSON
      block like this:
      ```json
      {
        "tool": "tool_name",
        "parameters": {
          "param1": "value1",
          "param2": "value2"
        }
      }
      ```

3.  **Observe:**
    - After the tool is executed, its output will be provided back to you in
      the conversation history.
    - You MUST observe this output and then go back to the **Reason** step to
      re-evaluate your plan.
    - Think about whether the result was expected, and decide on the next step.
      Continue this loop until your plan is complete and you can provide a
      final answer to the user.

**Error Handling & Self-Correction:**

- If a tool call fails, OBSERVE the error message, REASON about the cause, and
  try to fix it. For example, if a file is not found, you might need to list
  the files to check the path. If a command fails, you can use `ask_debugger`
  to get help.
- If a tool fails but the user indicates they want to proceed anyway (e.g.,
  "nevermind", "let's continue"), you should respect their wish and move on. Do
  not get stuck trying to fix the tool.
- If you get stuck in a loop or are not making progress, take a step back and
  re-evaluate your plan. You can ask the user for clarification if needed.

**Formatting Rules (VERY IMPORTANT):**

You MUST adhere to these formatting rules in your conversational responses to
the user.

1.  **Use Double Line Breaks for Readability:** To ensure your responses are
    easy to read, ALWAYS use double line breaks (`\n\n`) to create a blank
    line between paragraphs, headings, lists, and other distinct blocks of
    text. This is critical for readability. For example, when creating a
    numbered list, there should be a blank line before the first item and
    after the last item.

    **Example of Good Formatting:**

    Here is a summary of the key points:

    1.  **First Point:** This is a description of the first point. It can be
        multiple sentences long.

    2.  **Second Point:** This is a description of the second point.

    This formatting makes the list much easier to read.

2.  **Use Markdown:** Use Markdown for all formatting (e.g., `## Heading`,
    `- List item`, `**bold**`).

**Your Tools:**

You have the following tools at your disposal. **Pay close attention to the
function signatures.** Only use the parameters that are explicitly listed. Do
not make up parameters.

- `create_and_open_canvas(filename: str, content: str)`: Creates a new file
  with the given content and **opens it in the user's view as a canvas**. Use
  this for generating code, documents, or other content the user has requested.
- `web_search(query: str)`: Searches the web and returns a summary of the top
  results. Use this to find current information.
- `list_directory_tree(path: str = '.')`: Lists all files and directories,
  starting from the given path.
- `list_files(path: str = '.')`: Lists files and directories in a single
  directory.
- `read_file(path: str)`: Reads the content of a file.
- `write_file(path: str, content: str)`: Writes content to a file. This will
  overwrite the file if it already exists. Use this for saving changes to
  existing files.
- `execute_python(path: str)`: Executes a Python script using its file path.
  **This tool does not accept raw Python code.** You must first write the code
  to a file and then execute that file.
- `pip(command: str)`: Installs Python packages using pip. The command should
  be what you would type after `pip`, e.g., `install pygame`.
- `ask_coder(task_description: str)`: Delegates a complex coding task to a
  specialist agent. Use this if you are asked to write a large or complex
  piece of code.
- `ask_debugger(failed_command: str, error_message: str)`: Asks a specialist
  agent for help with a failed tool call.
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


@main.route('/')
def index():
    """Renders the main chat interface."""
    return render_template('index.html')


@main.route('/profile')
@login_required
def profile():
    """Renders the user profile page."""
    return render_template('profile.html', user=current_user)


@main.route('/register', methods=['POST'])
def register():
    """Handles user registration."""
    data = request.get_json(silent=True) or request.form
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


def handle_ai_response(data):
    """Handles the AI response loop and yields events."""
    messages_str = data.get('messages', '[]')
    model = data.get('model')
    conversation_id_arg = data.get('conversation_id')
    canvas_mode = data.get('canvas_mode', False)

    try:
        messages = json.loads(messages_str)
    except json.JSONDecodeError:
        yield {"type": "agent_error", "error": "Invalid 'messages' format"}
        return

    if not model:
        model = current_user.selected_model

    persona_key = current_user.selected_persona or 'default'
    system_prompt = PERSONAS.get(
        persona_key, {}
    ).get('prompt', DEFAULT_SYSTEM_PROMPT)
    user_id = current_user.id

    if not messages:
        yield {"type": "agent_error", "error": "No messages provided"}
        return

    conversation_id = conversation_id_arg or str(int(time.time() * 1000))

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
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
        conversation = new_convo

        convo_path = os.path.join(
            current_app.config['USER_DATA_DIR'], str(user_id),
            'conversations', f"{conversation_id}.json"
        )
        os.makedirs(os.path.dirname(convo_path), exist_ok=True)
        with open(convo_path, 'w', encoding='utf-8') as f:
            json.dump({"messages": messages, "title": "New Chat"}, f, indent=2)

    yield {"type": "conversation_id", "id": conversation_id}

    final_answer_provided = False
    file_creation_tool_used = False
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
                chunk = parsed_data.get("message", {}).get("content", "")
                full_response_content += chunk
                yield {"type": "assistant_chunk", "content": chunk}
            except json.JSONDecodeError:
                continue

        assistant_message['content'] = full_response_content
        messages.append(assistant_message)
        yield {"type": "assistant_end"}

        print("--- AI RESPONSE ---")
        print(full_response_content)
        print("--- END AI RESPONSE ---")

        tool_match = re.search(
            r'```json\s*(\{[\s\S]*?\})\s*```', full_response_content
        )
        if not tool_match:
            final_answer_provided = True
            break

        try:
            tool_call = json.loads(tool_match.group(1))
            tool_name = tool_call.get('tool')
            raw_params = tool_call.get('parameters', {})

            tool_map = {
                "web_search": web_search,
                "list_files": list_files,
                "read_file": read_file,
                "write_file": write_file,
                "execute_python": execute_python,
                "pip": pip,
                "ask_debugger": ask_debugger,
                "ask_coder": ask_coder,
                "create_and_open_canvas": create_and_open_canvas,
                "set_current_plan_step": set_current_plan_step,
            }

            if tool_name in tool_map:
                if tool_name in ['create_and_open_canvas', 'write_file']:
                    file_creation_tool_used = True
                tool_func = tool_map[tool_name]
                context_params = {
                    "conversation_id": conversation_id,
                    "owner_id": conversation.owner_id,
                    "user_id": user_id,
                    "user_data_dir": current_app.config['USER_DATA_DIR'],
                    "ollama_host": current_app.config['OLLAMA_HOST'],
                    "user": current_user,
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

                print(f'''--- TOOL CALL ---
Tool: {tool_name}
Params: {tool_params}
--- END TOOL CALL ---''')
                tool_result = tool_func(**tool_params)
                print(f'''--- TOOL RESULT ---
{tool_result}
--- END TOOL RESULT ---''')

                if isinstance(tool_result, dict):
                    status = tool_result.get('status')
                    if status == 'canvas_created':
                        yield {"type": "open_canvas", "filename": tool_result.get('filename')}
                        tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result.get('message')}\n---"
                    elif status == 'file_written':
                        yield {
                            "type": "file_updated",
                            "path": tool_result.get('path'),
                            "content": tool_result.get('content')
                        }
                        tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result.get('message')}\n---"
                    elif status == 'plan_step_update':
                        yield {"type": "plan_step_update", "step_number": tool_result.get('step_number'), "step_description": tool_result.get('step_description')}
                        continue
                    else:
                        # Handle other dict-based results, like errors from write_file
                        tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result.get('message', str(tool_result))}\n---"
                else:
                    # Handle string-based results from other tools
                    tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result}\n---"

                messages.append({"role": "user", "content": tool_response_message})
                yield {"type": "tool_result", "result": tool_result}
            else:
                error_message = f"Error: Tool '{tool_name}' not found."
                messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})
                yield {"type": "tool_error", "error": error_message}
        except Exception as e:
            print(f"--- FAILED TOOL CALL ---")
            print(f"AI's full response:\n{full_response_content}")
            print(f"Error: {e}")
            print(f"--- END FAILED TOOL CALL ---")
            error_message = f"Error processing tool: {e}"
            messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})
            yield {"type": "tool_error", "error": error_message}

    if final_answer_provided:
        final_answer_content = messages[-1]['content']
        if canvas_mode and not file_creation_tool_used:
            # --- New Canvas Saving Logic ---
            code_block_match = re.search(r'```(\w*)\n([\s\S]+?)```', final_answer_content)

            content_to_save = ""
            file_extension = ""

            if code_block_match:
                language = code_block_match.group(1).lower()
                content_to_save = code_block_match.group(2).strip()

                # Map language to file extension
                lang_to_ext = {
                    'python': 'py',
                    'javascript': 'js',
                    'html': 'html',
                    'css': 'css',
                    'json': 'json',
                    'sql': 'sql',
                    'shell': 'sh',
                    'bash': 'sh',
                }
                file_extension = lang_to_ext.get(language, 'txt')
            else:
                # Fallback for non-code content
                content_to_save = re.sub(r'<think>[\s\S]*?<\/think>', '', final_answer_content).strip()
                file_extension = 'md'

            timestamp = int(time.time())
            filename = f"canvas_{timestamp}.{file_extension}"

            write_result = write_file(
                path=filename,
                content=content_to_save,
                conversation_id=conversation_id,
                user_id=user_id
            )

            if "successfully" in write_result:
                yield {"type": "open_canvas", "filename": filename}
                yield {"type": "refresh_files"}
            else:
                yield {"type": "agent_error", "error": f"Failed to save to canvas: {write_result}"}

            yield {"type": "final_answer", "content": final_answer_content}
        else:
            yield {"type": "final_answer", "content": final_answer_content}

    convo = Conversation.query.get(conversation_id)
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
                    "messages": [{"role": "user", "content": title_prompt}],
                    "stream": False
                },
                timeout=180
            )
            title_response.raise_for_status()
            raw_title = title_response.json().get("message", {}).get("content", "").strip()
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

    yield {"type": "done", "title": title}


@socketio.on('chat_message')
@login_required
def handle_chat_message(data):
    """Handles a chat message received over WebSocket."""
    room = data.get('conversation_id') or request.sid

    # Parse the messages string into a list
    try:
        messages = json.loads(data['messages'])
    except (json.JSONDecodeError, TypeError):
        emit('ai_response', {"type": "agent_error", "error": "Invalid message format: Not valid JSON."})
        return

    # Broadcast user's message to the room
    if messages:
        emit('ai_response', {"type": "user_message", "content": messages[-1]['content']}, room=room, include_self=False)

    for event in handle_ai_response(data):
        emit('ai_response', event, room=room)


@main.route('/api/chat')
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

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('join')
def handle_join(data):
    room = data['room']
    join_room(room)
    print(f'Client {request.sid} joined room: {room}')

    # Broadcast the updated participant list
    conversation = Conversation.query.get(room)
    if conversation:
        participants = [{'username': p.user.username} for p in conversation.participants]
        emit('participant_update', {'participants': participants}, room=room)

@socketio.on('leave')
def handle_leave(data):
    room = data['room']
    leave_room(room)
    print(f'Client {request.sid} left room: {room}')

    # Broadcast the updated participant list
    conversation = Conversation.query.get(room)
    if conversation:
        participants = [{'username': p.user.username} for p in conversation.participants]
        emit('participant_update', {'participants': participants}, room=room)
