import os
import json
import re
import shutil
import time
import sys
import requests
from flask import (
    Blueprint, Response, request, render_template, jsonify, current_app
)
from flask_login import login_user, logout_user, current_user, login_required
from extensions import db
from models import User, Conversation, ConversationParticipant
from tools import (
    get_workspace_path, list_files, read_file, write_file,
    execute_python, pip, ask_debugger, ask_coder, web_search,
    list_directory_tree, create_and_open_canvas, set_current_plan_step
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

1.  **Use Double Line Breaks for Readability:** To ensure your responses are easy to read, ALWAYS use double line breaks (`\n\n`) to create a blank line between paragraphs, headings, lists, and other distinct blocks of text. This is critical for readability. For example, when creating a numbered list, there should be a blank line before the first item and after the last item.

    **Example of Good Formatting:**

    Here is a summary of the key points:

    1.  **First Point:** This is a description of the first point. It can be multiple sentences long.

    2.  **Second Point:** This is a description of the second point.

    This formatting makes the list much easier to read.

2.  **Use Markdown:** Use Markdown for all formatting (e.g., `## Heading`, `- List item`, `**bold**`).

**Your Tools:**

You have the following tools at your disposal. **Pay close attention to the function signatures.** Only use the parameters that are explicitly listed. Do not make up parameters.

- `create_and_open_canvas(filename: str, content: str)`: Creates a new file with the given content and **opens it in the user's view as a canvas**. Use this for generating code, documents, or other content the user has requested.
- `web_search(query: str)`: Searches the web and returns a summary of the top results. Use this to find current information.
- `list_directory_tree(path: str = '.')`: Lists all files and directories, starting from the given path.
- `list_files(path: str = '.')`: Lists files and directories in a single directory.
- `read_file(path: str)`: Reads the content of a file.
- `write_file(path: str, content: str)`: Writes content to a file. This will overwrite the file if it already exists. Use this for saving changes to existing files.
- `execute_python(path: str)`: Executes a Python script using its file path. **This tool does not accept raw Python code.** You must first write the code to a file and then execute that file.
- `pip(command: str)`: Installs Python packages using pip. The command should be what you would type after `pip`, e.g., `install pygame`.
- `ask_coder(task_description: str)`: Delegates a complex coding task to a specialist agent. Use this if you are asked to write a large or complex piece of code.
- `ask_debugger(failed_command: str, error_message: str)`: Asks a specialist agent for help with a failed tool call.
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
                        params['selected_model'] = current_user.selected_model
                        params['user_id'] = current_user.id

                        print(f"DEBUG: AI is attempting to call tool '{tool_name}' with parameters: {params}"); sys.stdout.flush()

                        yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'params': params})}\n\n"

                        tool_map = {
                            "web_search": web_search, "list_directory_tree": list_directory_tree,
                            "list_files": list_files, "read_file": read_file, "write_file": write_file,
                            "execute_python": execute_python, "pip": pip,
                            "ask_debugger": ask_debugger, "ask_coder": ask_coder,
                            "create_and_open_canvas": create_and_open_canvas,
                            "set_current_plan_step": set_current_plan_step,
                        }

                        if tool_name in tool_map:
                            tool_func = tool_map[tool_name]
                            # 3. OBSERVE
                            tool_result = tool_func(**params)

                            tool_result_str = str(tool_result)
                            if len(tool_result_str) > 500:
                                tool_result_str = tool_result_str[:500] + "..."
                            print(f"DEBUG: Tool '{tool_name}' returned: {tool_result_str}"); sys.stdout.flush()

                            if isinstance(tool_result, dict):
                                if tool_result.get('status') == 'canvas_created':
                                    yield f"data: {json.dumps({'type': 'open_canvas', 'filename': tool_result.get('filename')})}\n\n"
                                    tool_response_message = f"TOOL RESPONSE:\n---\n{tool_result.get('message')}\n---"
                                elif tool_result.get('status') == 'plan_step_update':
                                    yield f"data: {json.dumps({'type': 'plan_step_update', 'step_number': tool_result.get('step_number'), 'step_description': tool_result.get('step_description')})}\n\n"
                                    # Continue to the next iteration of the loop immediately
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
                    # If loop finishes (e.g., max_iterations), send the last message as the final answer.
                    yield f"data: {json.dumps({'type': 'final_answer', 'content': messages[-1]['content']})}\n\n"

            except Exception as e:
                # Catch any unexpected errors during the stream and report them.
                yield f"data: {json.dumps({'type': 'agent_error', 'error': str(e)})}\n\n"
            finally:
                # --- Save Final Conversation ---
                conversation_path = os.path.join(current_app.config['USER_DATA_DIR'], str(user_id), 'conversations', f"{conversation_id}.json")
                os.makedirs(os.path.dirname(conversation_path), exist_ok=True)
                is_new_conversation = not Conversation.query.get(conversation_id)

                if not is_new_conversation:
                    with open(conversation_path, 'r', encoding='utf-8') as f:
                        convo_data = json.load(f)
                else:
                    convo_data = {"messages": [], "title": "New Chat"}

                title = convo_data.get("title", "New Chat")

                if is_new_conversation:
                    if len(messages) >= 2:
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

                    # Create new conversation in the database
                    new_convo = Conversation(id=conversation_id, title=title, owner_id=user_id)
                    db.session.add(new_convo)

                    # Add the owner as a participant
                    owner_participant = ConversationParticipant(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        role='owner'
                    )
                    db.session.add(owner_participant)

                convo_data['messages'] = messages
                convo_data['title'] = title

                # For existing conversations, we might need to update the title
                if not is_new_conversation:
                    convo = Conversation.query.get(conversation_id)
                    if convo and convo.title != title:
                        convo.title = title

                db.session.commit()

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

@main.route('/api/workspace/file', methods=['GET'])
@login_required
def get_workspace_file_content():
    """Gets the content of a file in a conversation's workspace."""
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

    workspace_path = get_workspace_path(conversation_id)
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
    """Saves content to a file in a conversation's workspace."""
    data = request.get_json()
    path = data.get('path')
    content = data.get('content')
    conversation_id = data.get('conversation_id')

    if not path or content is None or not conversation_id:
        return jsonify({"error": "Path, content, and conversation_id are required"}), 400

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied. Only the owner can save files."}), 403

    workspace_path = get_workspace_path(conversation_id)
    if not workspace_path:
        return jsonify({"error": "Invalid conversation"}), 400

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return jsonify({"error": "Access denied"}), 403

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"success": True, "message": f"File '{path}' saved successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main.route('/api/workspace/file', methods=['DELETE'])
@login_required
def delete_workspace_file():
    """Deletes a file or directory from a conversation's workspace."""
    data = request.get_json()
    path = data.get('path')
    conversation_id = data.get('conversation_id')
    
    if not path or not conversation_id:
        return jsonify({"error": "Path and conversation_id are required"}), 400

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied. Only the owner can delete files."}), 403

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
    """Returns a list of all conversations the user is a participant in."""
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
    """Returns the content of a specific conversation."""
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    is_participant = any(p.user_id == current_user.id for p in conversation.participants)
    if not is_participant:
        return jsonify({"error": "Access denied"}), 403

    owner_id = conversation.owner_id
    convo_path = os.path.join(current_app.config['USER_DATA_DIR'], str(owner_id), 'conversations', f"{session_id}.json")

    if os.path.exists(convo_path):
        with open(convo_path, 'r', encoding='utf-8') as f:
            convo_data = json.load(f)
            participant_link = next((p for p in conversation.participants if p.user_id == current_user.id), None)
            convo_data['role'] = participant_link.role if participant_link else None
            return jsonify(convo_data)

    return jsonify({"error": "Conversation data file not found"}), 404

@main.route('/api/users', methods=['GET'])
@login_required
def get_users():
    """Returns a list of all users, excluding the current user."""
    users = User.query.all()
    users_list = [{"id": user.id, "username": user.username} for user in users if user.id != current_user.id]
    return jsonify(users_list)

@main.route('/api/conversation/<session_id>/share', methods=['POST'])
@login_required
def share_conversation(session_id):
    """Shares a conversation with another user."""
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied. Only the owner can share."}), 403

    data = request.get_json()
    user_id_to_share_with = data.get('user_id')
    if not user_id_to_share_with:
        return jsonify({"error": "user_id is required"}), 400

    user_to_share_with = User.query.get(user_id_to_share_with)
    if not user_to_share_with:
        return jsonify({"error": "User to share with not found"}), 404

    is_already_participant = any(p.user_id == user_id_to_share_with for p in conversation.participants)
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
        return jsonify({"error": "Access denied. Only the owner can delete."}), 403

    user_data_dir = os.path.join(current_app.config['USER_DATA_DIR'], str(conversation.owner_id))
    convo_path = os.path.join(user_data_dir, 'conversations', f"{session_id}.json")
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
