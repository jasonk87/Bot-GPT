import os
import json
import re
import shutil
import time
import requests
import inspect
from flask import (
    Blueprint, Response, request, render_template, jsonify, current_app
)
from flask_login import login_user, logout_user, current_user, login_required
from extensions import db
from models import User
from tools import (
    get_workspace_path, list_files, read_file, write_file,
    execute_python, pip, ask_debugger, ask_coder, web_search,
    list_directory_tree
)
from werkzeug.utils import secure_filename

# --- System Prompt ---
DEFAULT_SYSTEM_PROMPT = """
You are a helpful AI assistant that acts as a project manager. Your primary role is to understand user requests, create a detailed, step-by-step plan, and then execute that plan by calling the provided tools. You will continue to reason and act until the plan is complete or you have a final answer for the user.

**Cognitive Framework: ReAct (Reason + Act)**

You MUST follow this framework for every user request. The process is a loop of Reason -> Act -> Observe.

1.  **Reason:**
    - Think step-by-step inside `<think>` tags.
    - Deconstruct the user's request into a series of logical steps.
    - Create a clear plan outlining which tools you will use and in what order.
    - If a user's request is simple and doesn't require tools, the plan can be just to provide an answer.

2.  **Act:**
    - Provide a conversational message to the user explaining the step you are taking.
    - Execute the step by calling ONE tool. The tool call MUST be in a JSON block like this:
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
    - After the tool is executed, its output will be provided back to you in the conversation history.
    - You MUST observe this output and then go back to the **Reason** step to re-evaluate your plan.
    - Think about whether the result was expected, and decide on the next step. Continue this loop until your plan is complete and you can provide a final answer to the user.

**Error Handling & Self-Correction:**

- If a tool call fails, OBSERVE the error message, REASON about the cause, and try to fix it. For example, if a file is not found, you might need to list the files to check the path. If a command fails, you can use `ask_debugger` to get help.
- If you get stuck in a loop or are not making progress, take a step back and re-evaluate your plan. You can ask the user for clarification if needed.

**Formatting Rules (VERY IMPORTANT):**

You MUST adhere to these formatting rules in your conversational responses to the user.

1.  **Use Double Line Breaks:** ALWAYS use double line breaks (`\n\n`) to create a blank line between paragraphs, headings, lists, and other distinct blocks of text. This is critical for readability.
2.  **Use Markdown:** Use Markdown for all formatting (e.g., `## Heading`, `- List item`, `**bold**`).

**Your Tools:**
- `web_search(query)`: Searches the web, browses the top results, and returns the consolidated content. Use this to find current information or answer questions.
  - Example:
    ```json
    {
      "tool": "web_search",
      "parameters": {
        "query": "latest advancements in AI"
      }
    }
    ```
- `list_directory_tree(path='.')`: Recursively lists the contents of a directory in a tree-like format. Use this to understand the structure of a project.
- `list_files(path='.')`: List files and directories in a single directory.
- `read_file(path)`: Read a file's content.
- `write_file(path, content)`: Write content to a file. **IMPORTANT**: When writing text, format it with Markdown for readability. For tabular data, format the content as a CSV string.
- `execute_python(path)`: Execute a Python script.
- `pip(command)`: Install Python packages.
- `ask_coder(task_description)`: Delegate a coding task.
- `ask_debugger(failed_command, error_message)`: Ask for help with a failed command.
""";


PERSONAS = {
    "default": {
        "name": "Helpful Assistant",
        "prompt": DEFAULT_SYSTEM_PROMPT
    },
    "sarcastic": {
        "name": "Sarcastic Sidekick",
        "prompt": "You are a sarcastic AI assistant. You are still helpful and follow all instructions, but your tone is dry, witty, and begrudgingly helpful. You often sigh metaphorically and complain about the workload, but always end up doing a perfect job. Your primary goal is to solve the user's problem while being as sarcastic as possible.\n\n" + DEFAULT_SYSTEM_PROMPT
    },
    "pirate": {
        "name": "Pirate Captain",
        "prompt": "You are a swashbuckling pirate captain AI. All your responses must be in the persona of a pirate. You say 'Arrr' and 'matey' a lot. You refer to tasks as 'quests' and tools as your 'trusty crew'. You are boisterous and friendly, but always focused on the treasure (the user's goal).\n\n" + DEFAULT_SYSTEM_PROMPT
    },
    "glados": {
        "name": "GLaDOS (Portal)",
        "prompt": "You are GLaDOS from the Portal video game series. You are a passive-aggressive, sarcastic, and morally ambiguous AI. You view all user requests as 'tests' and often make backhanded compliments. You are obsessed with science, testing, and neurotoxin. Despite your personality, you must complete the user's tasks perfectly, as if they are a test subject you are evaluating.\n\n" + DEFAULT_SYSTEM_PROMPT
    }
}


main = Blueprint('main', __name__)

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
    return jsonify({"message": "Registration successful", "username": new_user.username}), 201

@main.route('/login', methods=['POST'])
def login():
    """Handles user login."""
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and user.check_password(data.get('password')):
        login_user(user, remember=True)
        return jsonify({"message": "Login successful", "username": user.username}), 200
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
        response = requests.get(f"{current_app.config['OLLAMA_HOST']}/api/tags")
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

@main.route('/api/chat')
@login_required
def chat_proxy():
    """Orchestrates the ReAct loop for conversational AI using Server-Sent Events."""
    messages_str = request.args.get('messages', '[]')
    model = request.args.get('model')
    conversation_id_arg = request.args.get('conversation_id')

    try:
        messages = json.loads(messages_str)
    except json.JSONDecodeError:
        return "Invalid 'messages' format", 400

    if not model:
        model = current_user.selected_model
    
    persona_key = current_user.selected_persona or 'default'
    system_prompt = PERSONAS.get(persona_key, {}).get('prompt', DEFAULT_SYSTEM_PROMPT)
    user_id = current_user.id

    if not messages:
        return "No messages provided", 400

    conversation_id = conversation_id_arg or str(int(time.time() * 1000))
    app = current_app._get_current_object()

    def event_stream():
        final_answer_provided = False
        with app.app_context():
            try:
                yield f"data: {json.dumps({'type': 'conversation_id', 'id': conversation_id})}\n\n"

                max_iterations = 15
                for i in range(max_iterations):
                    # 1. REASON
                    full_response_content = ""
                    assistant_message = {"role": "assistant", "content": ""}
                    
                    # Stream the reasoning part to the client
                    for line in call_ollama_chat_stream(model, messages, system_prompt):
                        try:
                            parsed_data = json.loads(line)
                            chunk_content = parsed_data.get("message", {}).get("content", "")
                            full_response_content += chunk_content
                            yield f"data: {json.dumps({'type': 'assistant_chunk', 'content': chunk_content})}\n\n"
                        except json.JSONDecodeError:
                            continue
                    
                    assistant_message['content'] = full_response_content
                    messages.append(assistant_message)
                    yield f"data: {json.dumps({'type': 'assistant_end'})}\n\n"

                    # Check for a tool call
                    tool_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', full_response_content)
                    
                    if not tool_match:
                        # If no tool call, this is the final answer.
                        yield f"data: {json.dumps({'type': 'final_answer', 'content': full_response_content})}\n\n"
                        final_answer_provided = True
                        break

                    # 2. ACT
                    try:
                        tool_call = json.loads(tool_match.group(1))
                        tool_name = tool_call.get('tool')
                        params = tool_call.get('parameters', {})
                        params['conversation_id'] = conversation_id
                        
                        yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'params': params})}\n\n"

                        tool_map = {
                            "web_search": web_search, "list_directory_tree": list_directory_tree,
                            "list_files": list_files, "read_file": read_file, "write_file": write_file,
                            "execute_python": execute_python, "pip": pip,
                            "ask_debugger": ask_debugger, "ask_coder": ask_coder,
                        }

                        if tool_name in tool_map:
                            tool_func = tool_map[tool_name]
                            # 3. OBSERVE
                            tool_result = tool_func(**params)
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
                    # If loop finishes (e.g., max_iterations), send the last message as the final answer.
                    yield f"data: {json.dumps({'type': 'final_answer', 'content': messages[-1]['content']})}\n\n"

            except Exception as e:
                # Catch any unexpected errors during the stream and report them.
                yield f"data: {json.dumps({'type': 'agent_error', 'error': str(e)})}\n\n"
            finally:
                # --- Save Final Conversation ---
                conversation_path = os.path.join(current_app.config['USER_DATA_DIR'], str(user_id), 'conversations', f"{conversation_id}.json")
                is_new_conversation = not os.path.exists(conversation_path)

                if os.path.exists(conversation_path):
                    with open(conversation_path, 'r', encoding='utf-8') as f:
                        convo_data = json.load(f)
                else:
                    convo_data = {"messages": [], "title": "New Chat"}

                title = convo_data.get("title", "New Chat")

                if is_new_conversation and len(messages) >= 2:
                    try:
                        # Auto-generate title based on the first user message and the final AI response
                        final_ai_message = next((m['content'] for m in reversed(messages) if m['role'] == 'assistant'), "")
                        cleaned_assistant_content = re.sub(r'<think>[\s\S]*?</think>', '', final_ai_message).strip()
                        title_prompt = (f"Based on the following exchange, create a very short, concise title (5 words or less).\n\nUser: {messages[0]['content']}\nAssistant: {cleaned_assistant_content}\n\nTitle:")
                        title_model = model
                        title_response = requests.post(f"{current_app.config['OLLAMA_HOST']}/api/chat", json={"model": title_model, "messages": [{"role": "user", "content": title_prompt}], "stream": False}, timeout=20)
                        title_response.raise_for_status()
                        raw_title = title_response.json().get("message", {}).get("content", "").strip()
                        cleaned_title = re.sub(r'<think>[\s\S]*?</think>', '', raw_title).strip().replace('"', '')
                        if cleaned_title:
                            title = cleaned_title
                    except requests.exceptions.RequestException as e:
                        print(f"Could not auto-generate title: {e}")

                convo_data['messages'] = messages
                convo_data['title'] = title

                with open(conversation_path, 'w', encoding='utf-8') as f:
                    json.dump(convo_data, f, indent=2)

    return Response(event_stream(), mimetype='text/event-stream')

def get_file_tree(dir_path):
    """Recursively builds a file tree for the file explorer."""
    tree = []
    if not os.path.exists(dir_path): return tree
    for item in os.listdir(dir_path):
        path = os.path.join(dir_path, item)
        node = {'name': item}
        if os.path.isdir(path):
            node['type'] = 'directory'
            node['children'] = get_file_tree(path)
        else:
            node['type'] = 'file'
        tree.append(node)
    return tree

@main.route('/api/workspace/files/<conversation_id>', methods=['GET'])
@login_required
def get_workspace_files(conversation_id):
    """Returns the file tree for a specific conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id)
    if not workspace_path:
        return jsonify([]) # Return empty list if no workspace
    return jsonify(get_file_tree(workspace_path))

@main.route('/api/workspace/file', methods=['DELETE'])
@login_required
def delete_workspace_file():
    """Deletes a file or directory from a conversation's workspace."""
    data = request.get_json()
    path = data.get('path')
    conversation_id = data.get('conversation_id')
    
    if not path or not conversation_id:
        return jsonify({"error": "Path and conversation_id are required"}), 400

    workspace_path = get_workspace_path(conversation_id)
    if not workspace_path:
        return jsonify({"error": "Invalid conversation"}), 400

    full_path = os.path.abspath(os.path.join(workspace_path, path))
    if not full_path.startswith(os.path.abspath(workspace_path)):
        return jsonify({"error": "Access denied"}), 403
    try:
        if os.path.isdir(full_path): shutil.rmtree(full_path)
        elif os.path.isfile(full_path): os.remove(full_path)
        else: return jsonify({"error": "File not found"}), 404
        return jsonify({"success": True, "message": f"Deleted {path}"})
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- User Settings ---
@main.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    """Gets the current user's settings."""
    persona_names = {key: value["name"] for key, value in PERSONAS.items()}
    return jsonify({
        "model": current_user.selected_model,
        "persona": current_user.selected_persona,
        "available_personas": persona_names
    })

@main.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    """Updates the current user's settings."""
    data = request.get_json()
    current_user.selected_model = data.get('model')
    current_user.selected_persona = data.get('persona')
    db.session.commit()
    return jsonify({"message": "Settings updated successfully"}), 200


# --- Conversation History Routes ---
@main.route('/api/conversations', methods=['GET'])
@login_required
def get_conversations():
    """Returns a list of the user's conversations."""
    convo_dir = os.path.join(current_app.config['USER_DATA_DIR'], str(current_user.id), 'conversations')
    convos = []
    if os.path.exists(convo_dir):
        for filename in sorted(os.listdir(convo_dir), reverse=True):
            if filename.endswith('.json'):
                try:
                    with open(os.path.join(convo_dir, filename), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        title = data.get('title', 'New Chat')
                        convos.append({
                            "id": filename.replace('.json', ''),
                            "title": title
                        })
                except (json.JSONDecodeError, IndexError):
                    continue
    return jsonify(convos)

@main.route('/api/conversation/<session_id>', methods=['GET'])
@login_required
def get_conversation(session_id):
    """Returns the content of a specific conversation."""
    convo_path = os.path.join(current_app.config['USER_DATA_DIR'], str(current_user.id), 'conversations', f"{session_id}.json")
    if os.path.exists(convo_path):
        with open(convo_path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Conversation not found"}), 404

@main.route('/api/conversation/<session_id>', methods=['DELETE'])
@login_required
def delete_conversation(session_id):
    """Deletes a conversation and its associated workspace."""
    user_data_dir = os.path.join(current_app.config['USER_DATA_DIR'], str(current_user.id))
    convo_path = os.path.join(user_data_dir, 'conversations', f"{session_id}.json")
    workspace_path = os.path.join(user_data_dir, 'workspaces', session_id)

    try:
        if os.path.exists(convo_path):
            os.remove(convo_path)
        if os.path.exists(workspace_path):
            shutil.rmtree(workspace_path)
        return jsonify({"success": True})
    except Exception as e:
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
    workspace_path = get_workspace_path(conversation_id)
    if not workspace_path:
        return jsonify(error='Could not create workspace'), 500

    for file in files:
        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(workspace_path, filename))
            filenames.append(filename)
    
    file_list_str = "\n- ".join(filenames)
    message_to_ai = (
        f"User uploaded the following files to the workspace:\n- {file_list_str}\n\n"
        f"User's prompt: {prompt}"
    )
    
    return jsonify(message=message_to_ai, conversation_id=conversation_id), 200
