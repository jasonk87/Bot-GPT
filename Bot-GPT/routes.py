import os
import json
import re
import shutil
import time
import sys
import requests
import inspect
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
- If a tool fails but the user indicates they want to proceed anyway (e.g., "nevermind", "let's continue"), you should respect their wish and move on. Do not get stuck trying to fix the tool.
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

    # Check if this is a new conversation and save it immediately
    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        new_convo = Conversation(id=conversation_id, title="New Chat", owner_id=user_id)
        db.session.add(new_convo)
        owner_participant = ConversationParticipant(
            user_id=user_id,
            conversation_id=conversation_id,
            role='owner'
        )
        db.session.add(owner_participant)
        db.session.commit()

        # Also save the initial file
        conversation_path = os.path.join(current_app.config['USER_DATA_DIR'], str(user_id), 'conversations', f"{conversation_id}.json")
        os.makedirs(os.path.dirname(conversation_path), exist_ok=True)
        with open(conversation_path, 'w', encoding='utf-8') as f:
            json.dump({"messages": messages, "title": "New Chat"}, f, indent=2)

    # We need the conversation object for the owner_id later
    conversation = Conversation.query.get(conversation_id)

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

                    tool_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', full_response_content)
                    if not tool_match:
                        final_answer_provided = True
                        break

                    # 2. ACT
                    try:
                        tool_call = json.loads(tool_match.group(1))
                        tool_name = tool_call.get('tool')
                        raw_params = tool_call.get('parameters', {})

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

                            # Build the context and tool parameters dynamically
                            context_params = {
                                "conversation_id": conversation_id,
                                "owner_id": conversation.owner_id,
                                "user_data_dir": current_app.config['USER_DATA_DIR'],
                                "ollama_host": current_app.config['OLLAMA_HOST'],
                                "selected_model": current_user.selected_model,
                                "api_key": current_app.config['GOOGLE_API_KEY'],
                                "cse_id": current_app.config['GOOGLE_CSE_ID']
                            }

                            tool_params = {}
                            sig = inspect.signature(tool_func)
                            for param in sig.parameters:
                                if param in raw_params:
                                    tool_params[param] = raw_params[param]
                                elif param in context_params:
                                    tool_params[param] = context_params[param]

                            print(f"DEBUG: AI is attempting to call tool '{tool_name}' with parameters: {raw_params}"); sys.stdout.flush()

                            # 3. OBSERVE
                            tool_result = tool_func(**tool_params)

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
                    yield f"data: {json.dumps({'type': 'final_answer', 'content': messages[-1]['content']})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type': 'agent_error', 'error': str(e)})}\n\n"
            finally:
                # --- Save Final Conversation ---
                conversation = Conversation.query.get(conversation_id)
                if not conversation: return

                title = conversation.title
                if title == "New Chat" and len(messages) >= 2:
                    try:
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
                            conversation.title = title
                    except requests.exceptions.RequestException as e:
                        print(f"Could not auto-generate title: {e}")

                db.session.commit()

                conversation_path = os.path.join(current_app.config['USER_DATA_DIR'], str(user_id), 'conversations', f"{conversation_id}.json")
                with open(conversation_path, 'w', encoding='utf-8') as f:
                    json.dump({"messages": messages, "title": title}, f, indent=2)

    return Response(event_stream(), mimetype='text/event-stream')

# ... (rest of the file is the same)
