import os
import subprocess
import re
import inspect
import json
from flask import current_app
from extensions import socketio
from models import Conversation

# --- Dependencies for Web Browsing ---


try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    build = None
    HttpError = None

from utils import get_workspace_path

def is_safe_path(base, path, follow_symlinks=True):
    """Checks if a path is safe to access."""
    if follow_symlinks:
        return os.path.realpath(path).startswith(base)
    return os.path.abspath(path).startswith(base)


# --- Sandbox Tool Functions ---


def list_files(path='.', conversation_id=None, user_id=None):
    """Lists files in a given path within the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    base_path = os.path.abspath(workspace_path)
    target_path = os.path.abspath(os.path.join(base_path, path))

    if not target_path.startswith(base_path):
        return "Error: Access denied."

    try:
        files = os.listdir(target_path)
        if not files:
            return "Directory is empty."
        return "\n".join(files)
    except Exception as e:
        return f"Error: {str(e)}"

def list_directory_tree(path='.', conversation_id=None, user_id=None):
    """Recursively lists the contents of a directory in a tree format."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    base_path = os.path.abspath(workspace_path)
    start_path = os.path.abspath(os.path.join(base_path, path))

    if not start_path.startswith(base_path):
        return "Error: Access denied. Cannot list outside of workspace."
    if not os.path.isdir(start_path):
        return f"Error: The path '{path}' is not a valid directory."

    tree_string = ""
    for root, dirs, files in os.walk(start_path):
        level = root.replace(start_path, '').count(os.sep)
        indent = ' ' * 4 * (level)
        tree_string += f"{indent}{os.path.basename(root)}/\n"
        sub_indent = ' ' * 4 * (level + 1)
        for f in files:
            tree_string += f"{sub_indent}{f}\n"
    return tree_string.strip()


def get_file_tree(path, _original_start_path=None):
    """
    Generates a file tree structure for a given path.
    Returns a list of objects, where each object has 'name', 'type',
    and optionally 'children'.
    """
    if _original_start_path is None:
        _original_start_path = path

    tree = []
    if not os.path.exists(path) or not os.path.isdir(path):
        return []

    for item in sorted(os.listdir(path)):
        item_path = os.path.join(path, item)
        node = {
            "name": item,
            "path": os.path.relpath(
                item_path, start=_original_start_path
            ).replace(os.sep, '/')
        }
        if os.path.isdir(item_path):
            node["type"] = "directory"
            node["children"] = get_file_tree(item_path, _original_start_path)
        else:
            node["type"] = "file"
        tree.append(node)
    return tree


def read_file(path, conversation_id=None, user_id=None):
    """Reads the content of a file from the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return "Error: Access denied."

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"


def write_file(path, content, conversation_id=None, user_id=None):
    """Writes or overwrites a file in the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return {"status": "error", "message": "Error: Could not determine workspace."}

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return {"status": "error", "message": "Error: Access denied."}

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {
            "status": "file_written",
            "path": path,
            "content": content,
            "message": f"File '{path}' written successfully."
        }
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}

def create_and_open_canvas(
        filename, content, conversation_id=None, user_id=None):
    """
    Creates a new file in the workspace and signals the frontend to open it.
    """
    write_result = write_file(filename, content, conversation_id, user_id)

    if "successfully" in write_result:
        return {
            "status": "canvas_created",
            "filename": filename,
            "message": f"Successfully created canvas '{filename}'."
        }
    return write_result


def set_current_plan_step(step_number, step_description):
    """Informs the user about the current step of the plan being executed."""
    return {
        "status": "plan_step_update",
        "step_number": step_number,
        "step_description": step_description
    }


def set_plan(steps: list, conversation_id: str, requires_approval: bool = False, **kwargs):
    """
    Sets the agent's plan, sends it to the UI, and optionally waits for approval.
    """
    if not conversation_id:
        return "Error: conversation_id is required to set a plan."

    from utils import PLAN_APPROVALS
    PLAN_APPROVALS[conversation_id] = None  # Reset approval state

    socketio.emit('plan_updated', {'steps': steps, 'requires_approval': requires_approval}, room=conversation_id)

    if not requires_approval:
        return f"Plan with {len(steps)} steps has been set and sent to the user."

    # Wait for the user's response
    timeout = 300  # 5 minutes
    start_time = time.time()
    while time.time() - start_time < timeout:
        if PLAN_APPROVALS.get(conversation_id):
            break
        socketio.sleep(1)  # Yield control to allow other operations

    response = PLAN_APPROVALS.pop(conversation_id, 'timeout')
    if response == 'approve':
        return "Plan approved by the user. Proceeding with execution."
    elif response == 'reject':
        return "Plan rejected by the user. Please replan based on user feedback."
    else:
        return "No response from the user within the time limit. Assuming rejection."


def update_task_status(step_index: int, status: str, message: str = None, conversation_id: str = None, **kwargs):
    """
    Updates the status of a single task in the plan.
    Status can be one of: 'in_progress', 'completed', 'failed'.
    """
    if not conversation_id:
        return "Error: conversation_id is required to update a task status."

    payload = {'step_index': step_index, 'status': status, 'message': message}
    socketio.emit('task_updated', payload, room=conversation_id)
    return f"Status of step {step_index} updated to {status}."


def execute_python(path, conversation_id=None, user_id=None):
    """Executes a Python script within the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(
            os.path.abspath(workspace_path)) or not file_path.endswith(".py"):
        return "Error: Access denied or not a Python file."

    try:
        process = subprocess.run(
            ['python', file_path],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=workspace_path
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"


def pip(command, conversation_id=None, user_id=None):
    """Installs a Python package using pip."""
    try:
        command_list = ['pip'] + command.split() + ['--disable-pip-version-check']
        process = subprocess.run(
            command_list,
            capture_output=True,
            text=True,
            timeout=120
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"


def google_search(api_key, cse_id, query):
    """Performs a Google search and returns the results."""
    try:
        service = build("customsearch", "v1", developerKey=api_key)
        res = service.cse().list(q=query, cx=cse_id, num=3).execute()
        return res.get('items', [])
    except HttpError as e:
        raise ConnectionError(f"Google Search API HTTP error: {e.content.decode('utf-8')}") from e
    except Exception as e:
        raise ConnectionError(f"An unexpected error occurred during Google search: {e}") from e

def scrape_text_from_url(url):
    """Scrapes text content from a URL."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        return '\n'.join(chunk for chunk in chunks if chunk)
    except requests.exceptions.RequestException as e:
        return f"--- Could not get {url}: {e} ---\n\n"

def summarize_text(text, query, model, ollama_host):
    """Summarizes text using an AI model."""
    summarization_prompt = f"Based on the following web content, please provide a comprehensive answer to the user's query: '{query}'. Synthesize the information from the sources into a single, coherent response. Do not just list the content from each source. Your answer should be well-structured, easy to understand, and directly address the user's question. Format the response using Markdown for readability.\n\n--- WEB CONTENT ---\n{text}"
    try:
        response = requests.post(
            f"{ollama_host}/api/chat",
            json={"model": model, "messages": [{"role": "user", "content": summarization_prompt}], "stream": False},
            timeout=120
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Could not connect to the AI model to summarize: {e}") from e

def web_search(query, conversation_id=None, user_id=None, user=None):
    """
    Performs a web search using the Google Search API, scrapes the top
    results, and uses an AI model to summarize the answer.
    """
    api_key = current_app.config.get('GOOGLE_API_KEY')
    cse_id = current_app.config.get('GOOGLE_CSE_ID')

    if not api_key or not cse_id:
        return "Error: Google Search API key or CSE ID is not configured."

    if not all([requests, BeautifulSoup, build]):
        missing = [lib for lib, present in [("'requests'", requests), ("'beautifulsoup4'", BeautifulSoup), ("'google-api-python-client'", build)] if not present]
        return f"Error: Missing required libraries: {', '.join(missing)}."

    try:
        search_results = google_search(api_key, cse_id, query)
        if not search_results:
            return f"No results found for '{query}'."

        consolidated_content = ""
        for result in search_results:
            consolidated_content += scrape_text_from_url(result['link'])

        if not consolidated_content.strip():
            return "Could not retrieve any content from the search results."

        max_length = 8000
        if len(consolidated_content) > max_length:
            consolidated_content = consolidated_content[:max_length] + "..."

        current_model = user.selected_model if user else 'default_model_name'
        ollama_host = current_app.config['OLLAMA_HOST']

        summary = summarize_text(consolidated_content, query, current_model, ollama_host)
        return f"Based on my web search, here is the answer to your query about '{query}':\n\n{summary}"

    except ConnectionError as e:
        return f"Error during web search: {e}"
    except Exception as e:
        return f"An unexpected error occurred during web search: {e}"


def ask_debugger(failed_command, error_message, user=None, user_id=None):
    """Delegates a debugging task to a specialist agent."""
    debugger_prompt = (
        f"Fix this failed command:\n{failed_command}\n"
        f"Error:\n{error_message}\nReturn ONLY the corrected JSON."
    )
    try:
        current_model = user.selected_model if user else 'default_model_name'
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={
                "model": current_model,
                "messages": [{"role": "user", "content": debugger_prompt}],
                "stream": False
            },
            timeout=20
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        json_match = re.search(r'{[\s\S]*}', content)
        if json_match:
            return f"Debugger agent suggests this fix: {json_match.group(0)}"
        else:
            return f"Debugger agent could not find a fix. It responded: {content}"
    except Exception as e:
        return f"Error calling debugger agent: {e}"


def ask_coder(task_description, user=None, user_id=None):
    """Delegates a coding task to a specialist agent."""
    coder_prompt = (
        "Write Python code for the following task. Your code should be "
        "clean, well-formatted, and include comments where necessary. "
        "Return ONLY the raw code.\n"
        f"Task: {task_description}\nCode:"
    )
    try:
        current_model = user.selected_model if user else 'default_model_name'
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={
                "model": current_model,
                "messages": [{"role": "user", "content": coder_prompt}],
                "stream": False
            },
            timeout=30
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        code_match = re.search(r'```(?:\w*\n)?([\s\S]+)```', content)
        if code_match:
            return code_match.group(1).strip()
        return content.strip()
    except Exception as e:
        return f"Error calling Coder agent: {e}"

def call_ollama_chat_stream(model, messages, system_prompt):
    """Calls the Ollama chat API and yields response chunks."""
    try:
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

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            # Ollama streams Server Sent Events which are prefixed with
            # "data:".  Strip the prefix so the remaining content is valid
            # JSON regardless of whether Ollama is configured for SSE or
            # plain newline-delimited JSON responses.
            line = raw_line
            if line.startswith(':'):
                # Comment / heartbeat lines can be ignored entirely.
                continue
            if line.startswith('data:'):
                line = line[len('data:'):].strip()

            if not line or line == '[DONE]':
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON line: {line}")
                continue

            message_payload = payload.get("message", {})
            content_chunk = message_payload.get("content")
            if content_chunk:
                yield content_chunk

            if payload.get("done"):
                break
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Could not connect to Ollama: {e}") from e
    except Exception as e:
        raise ConnectionError(f"An unexpected error occurred: {e}") from e

def handle_tool_call(tool_call, conversation, user):
    """Handles a tool call from the AI."""
    tool_name = tool_call.get('tool')
    raw_params = tool_call.get('parameters', {})
    file_creation_tool_used = False

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
        "set_plan": set_plan,
        "update_task_status": update_task_status,
    }

    if tool_name in tool_map:
        if tool_name in ['create_and_open_canvas', 'write_file']:
            file_creation_tool_used = True
        tool_func = tool_map[tool_name]
        context_params = {
            "conversation_id": conversation.id,
            "owner_id": conversation.owner_id,
            "user_id": user.id,
            "user_data_dir": current_app.config['USER_DATA_DIR'],
            "ollama_host": current_app.config['OLLAMA_HOST'],
            "user": user,
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

        tool_result = tool_func(**tool_params)
        return tool_result, file_creation_tool_used
    else:
        raise ValueError(f"Tool '{tool_name}' not found.")