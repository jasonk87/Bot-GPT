import os
import subprocess
import re
from flask import current_app
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

# --- Helper function for conversation-specific workspaces ---
def get_workspace_path(conversation_id, user_id):
    """Constructs a path to a conversation-specific workspace."""
    if not user_id or not conversation_id:
        return None

    conversation = Conversation.query.get(conversation_id)
    if not conversation:
        owner_id = user_id
    else:
        owner_id = conversation.owner_id

    path = os.path.join(current_app.config['USER_DATA_DIR'], str(owner_id), 'workspaces', str(conversation_id))
    if not os.path.exists(path):
        os.makedirs(path)
    return path

# --- Sandbox Tool Functions ---
def list_files(path='.', conversation_id=None, user_id=None):
    """Lists files and directories in a given path within the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path: return "Error: Could not determine workspace."
    base_path = os.path.abspath(workspace_path)
    target_path = os.path.abspath(os.path.join(base_path, path))
    if not target_path.startswith(base_path): return "Error: Access denied."
    try:
        files = os.listdir(target_path)
        return "\n".join(files) if files else "Directory is empty."
    except Exception as e: return f"Error: {str(e)}"

def list_directory_tree(path='.', conversation_id=None, user_id=None):
    """Recursively lists the contents of a directory in a tree-like format."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path: return "Error: Could not determine workspace."
    
    base_path = os.path.abspath(workspace_path)
    start_path = os.path.abspath(os.path.join(base_path, path))

    if not start_path.startswith(base_path):
        return "Error: Access denied. Cannot list directories outside of the workspace."
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


def read_file(path, conversation_id=None, user_id=None):
    """Reads the content of a file from the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path: return "Error: Could not determine workspace."
    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)): return "Error: Access denied."
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return f.read()
    except Exception as e: return f"Error: {str(e)}"

def write_file(path, content, conversation_id=None, user_id=None):
    """Writes or overwrites a file in the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path: return "Error: Could not determine workspace."
    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)): return "Error: Access denied."
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f: f.write(content)
        return f"File '{path}' written successfully."
    except Exception as e: return f"Error: {str(e)}"

def create_and_open_canvas(filename, content, conversation_id=None, user_id=None):
    """
    Creates a new file in the workspace and signals the frontend to open it in the canvas.
    This tool should be used when the user asks to create something in a canvas.
    """
    write_result = write_file(filename, content, conversation_id, user_id)

    if "successfully" in write_result:
        return {
            "status": "canvas_created",
            "filename": filename,
            "message": f"Successfully created canvas '{filename}'."
        }
    else:
        return write_result

def set_current_plan_step(step_number, step_description):
    """
    Informs the user about the current step of the plan being executed.
    """
    return {
        "status": "plan_step_update",
        "step_number": step_number,
        "step_description": step_description
    }

def execute_python(path, conversation_id=None, user_id=None):
    """Executes a Python script within the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path: return "Error: Could not determine workspace."
    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)) or not file_path.endswith(".py"):
        return "Error: Access denied or not a Python file."
    try:
        process = subprocess.run(['python', file_path], capture_output=True, text=True, timeout=10, cwd=workspace_path)
        output = process.stdout
        if process.stderr: output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e: return f"Error: {str(e)}"

def pip(command, conversation_id=None, user_id=None):
    """Installs a Python package using pip."""
    try:
        command_list = ['pip'] + command.split() + ['--disable-pip-version-check']
        process = subprocess.run(
            command_list,
            capture_output=True, text=True, timeout=120
        )
        output = process.stdout
        if process.stderr: output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e: return f"Error: {str(e)}"

def web_search(query, conversation_id=None, user_id=None, selected_model=None):
    """
    Performs a web search using the Google Search API, scrapes the top results, sends the content to an AI model for summarization,
    and returns the summarized answer. This tool is intended to be called by an AI agent.
    """
    api_key = current_app.config.get('GOOGLE_API_KEY')
    cse_id = current_app.config.get('GOOGLE_CSE_ID')

    if not api_key or not cse_id:
        return "Error: Google Search API key or CSE ID is not configured. Please set them in the application configuration."

    if not all([requests, BeautifulSoup, build]):
        missing = []
        if not requests: missing.append("'requests'")
        if not BeautifulSoup: missing.append("'beautifulsoup4'")
        if not build: missing.append("'google-api-python-client'")
        return f"Error: The following required libraries are not installed: {', '.join(missing)}. The admin can install them via pip."

    try:
        # 1. Perform Google Search
        try:
            service = build("customsearch", "v1", developerKey=api_key)
            res = service.cse().list(q=query, cx=cse_id, num=3).execute()
            search_results = res.get('items', [])
        except HttpError as e:
            return f"Error: An HTTP error occurred while calling the Google Search API: {e.content.decode('utf-8')}"
        except Exception as e:
            return f"An unexpected error occurred during the Google search: {str(e)}"

        if not search_results:
            return f"No results found for '{query}'."

        # 2. Scrape Content from URLs
        consolidated_content = ""
        for result in search_results:
            try:
                url = result['link']
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                content_text = '\n'.join(chunk for chunk in chunks if chunk)
                consolidated_content += f"--- Content from {url} ---\n\n{content_text}\n\n"
            except requests.exceptions.RequestException as e:
                consolidated_content += f"--- Could not retrieve content from {url}: {e}---\n\n"
        
        if not consolidated_content.strip():
            return "Could not retrieve any content from the search results."

        # 3. Summarize with Ollama
        max_length = 8000
        if len(consolidated_content) > max_length:
            consolidated_content = consolidated_content[:max_length] + "... (content truncated)"

        current_model = selected_model or 'default_model_name'

        ollama_host = current_app.config['OLLAMA_HOST']
        
        summarization_prompt = (
            f"Based on the following web content, please provide a comprehensive answer to the user's query: '{query}'. "
            "Synthesize the information from the sources into a single, coherent response. Do not just list the content from each source. "
            "Your answer should be well-structured, easy to understand, and directly address the user's question. "
            "Format the response using Markdown for readability.\n\n"
            "--- WEB CONTENT ---\n"
            f"{consolidated_content}"
        )
        
        try:
            response = requests.post(
                f"{ollama_host}/api/chat",
                json={
                    "model": current_model,
                    "messages": [{"role": "user", "content": summarization_prompt}],
                    "stream": False
                },
                timeout=120
            )
            response.raise_for_status()
            summary = response.json().get("message", {}).get("content", "")
            return f"Based on my web search, here is the answer to your query about '{query}':\n\n{summary}"
        except requests.exceptions.RequestException as e:
            return f"Warning: Could not connect to the AI model to summarize the content. Returning raw search results.\n\n--- RAW WEB CONTENT ---\n{consolidated_content}"

    except Exception as e:
        return f"An unexpected error occurred during the web search and summarization process: {str(e)}"


def ask_debugger(failed_command, error_message, selected_model=None, user_id=None):
    """Delegates a debugging task to a specialist agent."""
    debugger_prompt = f"Fix this failed command:\n{failed_command}\nError:\n{error_message}\nReturn ONLY the corrected JSON."
    try:
        current_model = selected_model or 'default_model_name'
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={ "model": current_model, "messages": [{"role": "user", "content": debugger_prompt}], "stream": False },
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
        return f"Error calling debugger agent: {str(e)}"

def ask_coder(task_description, selected_model=None, user_id=None):
    """Delegates a coding task to a specialist agent."""
    coder_prompt = f"Write Python code for the following task. Your code should be clean, well-formatted, and include comments where necessary. Return ONLY the raw code.\nTask: {task_description}\nCode:"
    try:
        current_model = selected_model or 'default_model_name'
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={ "model": current_model, "messages": [{"role": "user", "content": coder_prompt}], "stream": False },
            timeout=30
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        code_match = re.search(r'```(?:\w*\n)?([\s\S]+)```', content)
        if code_match:
            return code_match.group(1).strip()
        return content.strip()
    except Exception as e:
        return f"Error calling Coder agent: {str(e)}"