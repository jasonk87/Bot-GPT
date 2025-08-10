import os
import subprocess
import re
import json
import shutil
from flask import current_app
from models import db, Conversation, GlobalKnowledge # <-- Ensure GlobalKnowledge is imported
import requests
import datetime
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
    Performs a web search, scrapes results, summarizes, and SAVES the summary
    to global knowledge for future RAG. Includes caching.
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
        final_query = query
        trigger_words = ['new', 'latest', 'current', 'recent']
        # Check if the query contains a trigger word AND does not already contain a year.
        if any(word in query.lower() for word in trigger_words) and not re.search(r'\b(20\d{2})\b', query):
            current_year = datetime.datetime.now().year
            final_query = f"{query} {current_year}"
            print(f"INFO: Auto-appended current year to query. New query: '{final_query}'")

        # --- NEW: Check for a cached result first for speed ---
        cached_knowledge = GlobalKnowledge.query.filter_by(query_text=query).first()
        if cached_knowledge:
            print(f"INFO: RAG - Found cached web search result for query: '{query}'")
            return (
                    f"Based on previous research, here is the answer to your "
                    f"query about '{query}':\n\n{cached_knowledge.response_content}")

        # 1. Perform Google Search (num=2 for speed)
        try:
            service = build("customsearch", "v1", developerKey=api_key)
            res = service.cse().list(q=query, cx=cse_id, num=2).execute()
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

                # Check if the content is likely text/html before parsing.
                content_type = response.headers.get('content-type', '').lower()
                if 'text' not in content_type and 'html' not in content_type:
                    print(f"WARNING: Skipping non-text URL: {url} (Content-Type: {content_type})")
                    consolidated_content += f"--- Skipped non-text content from {url} ---\n\n"
                    continue # Move to the next search result

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
                consolidated_content += f"--- Could not get {url}: {e}---\n\n"

        if not consolidated_content.strip():
            return "Could not retrieve any content from the search results."

        # 3. Summarize with Ollama
        max_length = 8000
        if len(consolidated_content) > max_length:
            consolidated_content = consolidated_content[:max_length] + "..."

        current_model = selected_model or 'default_model_name'
        ollama_host = current_app.config['OLLAMA_HOST']

        summarization_prompt = (
            f"""Based on the following web content, please provide a """
            f"comprehensive answer to the user's query: '{query}'. """
            f"Synthesize the information from the sources into a single, """
            f"coherent response. Do not just list the content from each """
            f"source. Your answer should be well-structured, easy to """
            f"understand, and directly address the user's question. Format """
            f"the response using Markdown for readability.\n\n"""
            f"--- WEB CONTENT ---\n"""
            f"{consolidated_content}"""
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

            # --- NEW: Save the successful summary to the database ---
            try:
                new_knowledge = GlobalKnowledge(
                    query_text=query,
                    response_content=summary
                )
                db.session.add(new_knowledge)
                db.session.commit()
                print(f"INFO: RAG - Successfully saved new web search result to GlobalKnowledge.")
            except Exception as db_error:
                db.session.rollback()
                print(f"ERROR: RAG - Failed to save to GlobalKnowledge: {db_error}")
            # --- END OF NEW CODE ---

            return (
                    f"Based on my web search, here is the answer to your "
                    f"query about '{query}':\n\n{summary}")
        except requests.exceptions.RequestException:
            return (
                    "Warning: Could not connect to the AI model to summarize. "
                    "Returning raw search results.\n\n"
                    f"--- RAW WEB CONTENT ---\n{consolidated_content}")

    except Exception as e:
        return f"An unexpected error occurred during web search: {e}"

# --- V2.0: New tools for the Main Agent ---
def write_file_main(path, content, conversation_id=None, user_id=None):
    """Writes or overwrites a file in the conversation's workspace. For the main agent."""
    return write_file(path, content, conversation_id, user_id)

def read_file_main(path, conversation_id=None, user_id=None):
    """Reads the content of a file from the conversation's workspace. For the main agent."""
    return read_file(path, conversation_id, user_id)

def convert_file_main(input_path, output_path, conversation_id=None, user_id=None):
    """Converts a file from one format to another. For the main agent."""
    return convert_file(input_path, output_path, conversation_id, user_id)



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

def convert_file(input_path: str, output_path: str, conversation_id=None, user_id=None):
    """
    Converts a file from one format to another using Pandoc.
    Supported formats are inferred from file extensions (e.g., .md to .pdf).
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    # Security: Ensure paths are within the workspace
    full_input_path = os.path.abspath(os.path.join(workspace_path, input_path))
    full_output_path = os.path.abspath(os.path.join(workspace_path, output_path))
    if not full_input_path.startswith(workspace_path) or not full_output_path.startswith(workspace_path):
        return "Error: Access denied. File paths must be within the workspace."

    if not os.path.exists(full_input_path):
        return f"Error: Input file '{input_path}' not found."

    command = [
        'pandoc',
        full_input_path,
        '-o',
        full_output_path
    ]

    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=True  # This will raise an exception if pandoc fails
        )
        return f"Successfully converted '{input_path}' to '{output_path}'."
    except FileNotFoundError:
        return "Error: The 'pandoc' command was not found. Please ensure Pandoc is installed on the server and in the system's PATH."
    except subprocess.CalledProcessError as e:
        return f"Error during conversion: {e.stderr}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"