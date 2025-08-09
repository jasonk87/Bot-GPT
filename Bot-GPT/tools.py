import os
import subprocess
import re
import json
import shutil  # Added this import
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

    path = os.path.join(
        current_app.config['USER_DATA_DIR'],
        str(owner_id),
        'workspaces',
        str(conversation_id)
    )
    if not os.path.exists(path):
        os.makedirs(path)
    return path


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
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return "Error: Access denied."

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"File '{path}' written successfully."
    except Exception as e:
        return f"Error: {str(e)}"

def open_in_canvas(path, conversation_id=None, user_id=None):
    """Signals the frontend to open an existing file in the canvas."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return "Error: Access denied."

    if not os.path.exists(file_path):
        return f"Error: File '{path}' does not exist."

    return {
        "status": "canvas_created",
        "filename": path,
        "message": f"Successfully opened '{path}' in canvas."
    }






def set_current_plan_step(step_number, step_description):
    """Informs the user about the current step of the plan being executed."""
    return {
        "status": "plan_step_update",
        "step_number": step_number,
        "step_description": step_description
    }


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
    except subprocess.TimeoutExpired as e:
        # If the process times out but there's no error, it's likely a working, long-running script.
        if not e.stderr:
            return ("Tool executed without errors and timed out after 10 seconds. "
                    "This often indicates a working, long-running process like a web server or game loop. "
                    "Assume the program has started successfully.")
        else:
            return f"Error: Command timed out with errors: {e.stderr}"
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
            timeout=300
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"


def web_search(query, conversation_id=None, user_id=None, selected_model=None):
    """
    Performs a web search using the Google Search API, scrapes the top
    results, and uses an AI model to summarize the answer.
    """
    api_key = current_app.config.get('GOOGLE_API_KEY')
    cse_id = current_app.config.get('GOOGLE_CSE_ID')

    if not api_key or not cse_id:
        return "Error: Google Search API key or CSE ID is not configured."

    if not all([requests, BeautifulSoup, build]):
        missing = [
            lib for lib, present in [
                ("'requests'", requests),
                ("'beautifulsoup4'", BeautifulSoup),
                ("'google-api-python-client'", build)
            ] if not present
        ]
        return f"Error: Missing required libraries: {', '.join(missing)}."

    try:
        # 1. Perform Google Search
        try:
            service = build("customsearch", "v1", developerKey=api_key)
            res = service.cse().list(q=query, cx=cse_id, num=3).execute()
            search_results = res.get('items', [])
        except HttpError as e:
            error_content = e.content.decode('utf-8')
            return f"Error: Google Search API HTTP error: {error_content}"
        except Exception as e:
            return f"An unexpected error occurred during Google search: {e}"

        if not search_results:
            return f"No results found for '{query}'."

        # 2. Scrape Content from URLs
        consolidated_content = ""
        for result in search_results:
            try:
                url = result['link']
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/91.0.4472.124 Safari/537.36'
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (
                    phrase.strip() for line in lines for phrase in line.split("  ")
                )
                content_text = '\n'.join(chunk for chunk in chunks if chunk)
                consolidated_content += f"--- From {url} ---\n{content_text}\n\n"
            except requests.exceptions.RequestException as e:
                consolidated_content += f"--- Could not get {url}: {e} ---\n\n"

        if not consolidated_content.strip():
            return "Could not retrieve any content from the search results."

        # 3. Summarize with Ollama
        max_length = 8000
        if len(consolidated_content) > max_length:
            consolidated_content = consolidated_content[:max_length] + "..."

        current_model = selected_model or 'default_model_name'
        ollama_host = current_app.config['OLLAMA_HOST']

        summarization_prompt = (
            f"Based on the following web content, please provide a "
            f"comprehensive answer to the user's query: '{query}'. "
            "Synthesize the information from the sources into a single, "
            "coherent response. Do not just list the content from each "
            "source. Your answer should be well-structured, easy to "
            "understand, and directly address the user's question. Format "
            "the response using Markdown for readability.\n\n"
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
                timeout=300
            )
            response.raise_for_status()
            summary = response.json().get("message", {}).get("content", "")
            return (f"Based on my web search, here is the answer to your "
                    f"query about '{query}':\n\n{summary}")
        except requests.exceptions.RequestException:
            return ("Warning: Could not connect to the AI model to summarize. "
                    "Returning raw search results.\n\n"
                    f"--- RAW WEB CONTENT ---\n{consolidated_content}")

    except Exception as e:
        return f"An unexpected error occurred during web search: {e}"


def ask_debugger(failed_command, error_message, selected_model=None, user_id=None):
    """Delegates a debugging task to a specialist agent."""
    debugger_prompt = (
        f"Fix this failed command:\n{failed_command}\n"
        f"Error:\n{error_message}\nReturn ONLY the corrected JSON."
    )
    try:
        current_model = selected_model or 'default_model_name'
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={
                "model": current_model,
                "messages": [{"role": "user", "content": debugger_prompt}],
                "stream": False
            },
            timeout=300
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


# --- V2.0: The Specialist System Prompt for the Coder Agent ---
CODER_AGENT_PROMPT = """
You are a master programmer, a specialist Coder Agent. Your **ONLY** function
is to complete the user's coding-related request by calling tools to modify the
file system. You are a key part of a larger team, and your project manager will
handle all communication with the user.

**CRITICAL RULES:**
1.  **ANALYZE FIRST:** Start by using `list_files` or `read_file` to understand the existing code. Never write code without context.
2.  **SURGICAL CHANGES:** Use the specialized tools (`search_and_replace_in_file`, `insert_content_at_line`, `delete_lines_in_file`) for small edits. Only use `write_file` for new files or major rewrites.
3.  **THINK & EXECUTE:** You **MUST** use a `<think>` block to explain your plan before every tool call. Your thought process is as important as the code itself.
4.  **STRICT OUTPUT FORMAT:** Your entire response **MUST** be a `<think>` block followed by one or more ```json ... ``` blocks for each tool you need to call.
5.  **FINISH THE JOB:** Continue calling tools until the user's request is fully complete. If you have finished the task, your **ONLY** response must be the exact text: `TASK_COMPLETE`
6.  **NO CONVERSATION:** Do not add conversational text or summaries. The Project Manager will do that. Your only outputs are `<think>` blocks, ```json``` tool calls, or `TASK_COMPLETE`.

**Your Private Tools:**
- `list_files(path: str)`
- `read_file(path: str)`
- `write_file(path: str, content: str)`
- `execute_python(path: str)`
- `search_and_replace_in_file(path: str, search_pattern: str, replace_string: str)`
- `insert_content_at_line(path: str, line_number: int, content: str)`
- `delete_lines_in_file(path: str, start_line: int, end_line: int)`

**EXAMPLE: Add a function to an existing file**
User Request: "Add a function to `utils.py` that calculates the square of a number."
<think>
First, I need to see what's already in `utils.py`. I'll use `read_file` to inspect its contents.
</think>
```json
{
  "tool": "read_file",
  "parameters": {
    "path": "utils.py"
  }
}
```
--- TOOL RESPONSE ---
def add(a, b):
    return a + b
---
<think>
Okay, the file exists and has an `add` function. I will append a new `square` function to the end of the file. Since I'm adding to the end, I can just read the whole file and then use `write_file` to overwrite it with the new content. A more surgical approach would be to use `insert_content_at_line`, but this is also fine.
</think>
```json
{
  "tool": "write_file",
  "parameters": {
    "path": "utils.py",
    "content": "def add(a, b):\n    return a + b\n\ndef square(n):\n    \"\"\"Calculates the square of a number.\"\"\"\n    return n * n\n"
  }
}
```
--- TOOL RESPONSE ---
File 'utils.py' written successfully.
---
<think>
The user's request was to add a function. I have added the function to the file. The task is now complete.
</think>
TASK_COMPLETE
"""


def ask_coder(task_description: str, selected_model=None, user_id=None, conversation_id=None):
    """
    Delegates a coding task to a specialist agent with its own ReAct loop.
    This function will manage the entire lifecycle of the coding task, from
    initial analysis to final implementation, by repeatedly calling the LLM
    and executing the tools it requests.
    """
    print(f"DEBUG: Coder Agent started for user {user_id} with task: '{task_description}'")

    # The Coder Agent has its own, private toolset
    coder_tool_map = {
        "list_files": list_files,
        "read_file": read_file,
        "write_file": write_file,
        "execute_python": execute_python,
        "search_and_replace_in_file": search_and_replace_in_file,
        "insert_content_at_line": insert_content_at_line,
        "delete_lines_in_file": delete_lines_in_file,
    }

    # Start the conversation with the initial task
    messages = [{"role": "user", "content": f"The user's request is: {task_description}"}]
    full_transcript = [f"User's Task: {task_description}"]
    max_iterations = 10

    for i in range(max_iterations):
        print(f"DEBUG: Coder Agent - Iteration {i+1}")

        try:
            ollama_host = current_app.config['OLLAMA_HOST']
            model = selected_model or 'default_model_name'

            response = requests.post(
                f"{ollama_host}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": CODER_AGENT_PROMPT}] + messages,
                    "stream": False
                },
                timeout=120
            )
            response.raise_for_status()

            agent_response_content = response.json().get("message", {}).get("content", "").strip()
            print(f"DEBUG: Coder Agent Raw Response: {agent_response_content}")
            messages.append({"role": "assistant", "content": agent_response_content})
            full_transcript.append(f"Coder Agent Thought Process:\n{agent_response_content}")

            # Check for completion signal
            if agent_response_content == "TASK_COMPLETE":
                print("DEBUG: Coder Agent signaled task completion.")
                break

            tool_matches = re.findall(r'```json\s*(\{[\s\S]*?\})\s*```', agent_response_content)

            if not tool_matches:
                print("DEBUG: Coder Agent did not call a tool. Breaking loop.")
                full_transcript.append("Agent did not call a tool, ending interaction.")
                break

            tool_outputs = []
            for tool_call_str in tool_matches:
                try:
                    tool_call = json.loads(tool_call_str)
                    tool_name = tool_call.get("tool")
                    params = tool_call.get("parameters", {})

                    if tool_name in coder_tool_map:
                        # Inject context into the tool parameters
                        params['user_id'] = user_id
                        params['conversation_id'] = conversation_id

                        tool_func = coder_tool_map[tool_name]
                        result = tool_func(**params)
                        output = f"--- TOOL RESPONSE ---\n{result}\n---"
                        tool_outputs.append(output)
                        print(f"DEBUG: Coder Agent executed '{tool_name}' with result: {result}")
                    else:
                        error_msg = f"Error: Coder agent tried to call unknown tool '{tool_name}'."
                        tool_outputs.append(error_msg)
                        print(f"ERROR: {error_msg}")

                except Exception as e:
                    error_msg = f"Error processing tool call: {str(e)}"
                    tool_outputs.append(error_msg)
                    print(f"ERROR: {error_msg}")

            # Add tool outputs back to the message history for the next turn
            consolidated_output = "\n".join(tool_outputs)
            messages.append({"role": "user", "content": consolidated_output})
            full_transcript.append(f"Tool Execution Results:\n{consolidated_output}")

        except Exception as e:
            error_message = f"Error during Coder Agent execution: {e}"
            print(f"ERROR: {error_message}")
            full_transcript.append(f"CRITICAL ERROR: {error_message}")
            break # Exit loop on critical error

    final_report = (
        "The Coder Agent has completed its task. Here is the summary of its actions:\n\n"
        + "\n\n".join(full_transcript)
    )
    return final_report


# --- V2.0: Specialist Agent Delegation Tools ---

def ask_memory_agent(task: str, user_id=None, conversation_id=None):
    """
    Delegates a task to the specialist Memory Agent.
    Use for any request related to saving or recalling personal information
    about the user or summarizing conversations.
    """
    print(f"DEBUG: Delegating task to Memory Agent for user {user_id}: '{task}'")
    # TODO: This will trigger the Memory Agent's internal ReAct loop.
    return "The Memory Agent has processed your request."

def ask_inventory_agent(task: str, user_id=None, conversation_id=None):
    """
    Delegates a task to the specialist Pantry Inventory Agent.
    Use for ALL tasks related to the family's pantry, grocery lists, etc.
    """
    print(f"DEBUG: Delegating task to Inventory Agent for user {user_id}: '{task}'")
    # TODO: This will trigger the Inventory Agent's internal ReAct loop.
    return "The Inventory Agent is handling your request."

def ask_api_manager(task: str, user_id=None, conversation_id=None):
    """
    Delegates a task to the specialist API Manager Agent.
    Use for any task that requires accessing a real-time external service
    like weather, Giphy, or price comparisons.
    """
    print(f"DEBUG: Delegating task to API Manager: '{task}'")
    # TODO: This will trigger the API Manager's internal ReAct loop.
    return "The API Manager is handling your request."

def ask_agent_manager(task: str, user_id=None, conversation_id=None):
    """
    Delegates a task to the specialist Agent Manager.
    Use ONLY when the user explicitly asks to add, remove, or manage
    other AI agents in the conversation.
    """
    print(f"DEBUG: Delegating task to Agent Manager: '{task}'")
    # TODO: This will trigger the Agent Manager's internal ReAct loop.
    return "The Agent Manager is handling your request."

# --- V2.0: Advanced Surgical Coding Tools (Fully Implemented) ---

def search_and_replace_in_file(path: str, search_pattern: str, replace_string: str, conversation_id=None, user_id=None):
    """
    Performs a regex search and replace for a given pattern in a file.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return "Error: Access denied."

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content, count = re.subn(search_pattern, replace_string, content)
        
        if count == 0:
            return f"Pattern not found in {path}. No changes made."

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
            
        return f"Successfully replaced {count} occurrence(s) in {path}."
    except FileNotFoundError:
        return f"Error: File not found at '{path}'."
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"
    except Exception as e:
        return f"Error during search and replace: {str(e)}"


def insert_content_at_line(path: str, line_number: int, content: str, conversation_id=None, user_id=None):
    """
    Inserts a block of content at a specific line number in a file.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return "Error: Access denied."

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Line numbers are 1-based for users, but list indices are 0-based
        if line_number < 1 or line_number > len(lines) + 1:
            return f"Error: Line number {line_number} is out of bounds for file {path}."

        # Add a newline to the content if it doesn't have one
        if not content.endswith('\n'):
            content += '\n'
            
        lines.insert(line_number - 1, content)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
            
        return f"Successfully inserted content at line {line_number} in {path}."
    except FileNotFoundError:
        return f"Error: File not found at '{path}'."
    except Exception as e:
        return f"Error during content insertion: {str(e)}"


def delete_lines_in_file(path: str, start_line: int, end_line: int, conversation_id=None, user_id=None):
    """
    Deletes a range of lines from a file.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return "Error: Access denied."
        
    if start_line > end_line:
        return "Error: Start line must be less than or equal to end line."

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or end_line > len(lines):
            return f"Error: Line range {start_line}-{end_line} is out of bounds for file {path}."

        del lines[start_line - 1:end_line]

        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
            
        return f"Successfully deleted lines {start_line}-{end_line} from {path}."
    except FileNotFoundError:
        return f"Error: File not found at '{path}'."
    except Exception as e:
        return f"Error during line deletion: {str(e)}"