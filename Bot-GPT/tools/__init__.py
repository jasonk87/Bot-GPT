# Bot-GPT/tools/__init__.py

import os
import sys
import subprocess
import re
import inspect
import json
import time
from flask import current_app
from extensions import socketio

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

try:
    import chromadb
except ImportError:
    chromadb = None

# google.generativeai import removed (unused and deprecated)

try:
    from PIL import Image
except ImportError:
    Image = None

# Import tool functions from sub-modules
from .web_search import web_search
from .file_system import (
    is_safe_path,
    list_files,
    list_directory_tree,
    get_file_tree,
    read_file,
    read_codebase,
    write_file,
    write_file,
    get_workspace_path,
    list_core_files,
    read_core_file,
)
from .git_integration import (
    git_clone,
    git_pull,
    git_push,
    git_commit,
    git_add,
)
from .senses import capture_screen
from .database import get_db_schema
from .sql_query import run_sql_query
from .shell import run_shell_command
from .self_healing import implement_and_test_code


# Functions moved from the old tools.py

# --- Memory Tools ---
def remember(scope, key, value, conversation_id=None, user_id=None, **kwargs):
    """
    Saves a fact to memory.
    Args:
        scope (str): 'user' for personal memory, 'project' for workspace memory.
        key (str): The label/keyword for this memory.
        value (str): The information to remember.
    """
    try:
        from memory import MemoryManager
        memory = MemoryManager(user_id=user_id)
        
        if scope == "project" and conversation_id:
             # We need to resolve the owner_id to find the project path
             # tools/__init__.py imports file_system which imports chat... circular import risk?
             # Let's rely on context to pass owner_id if possible, or assume user_id is owner
             # The context_params in handle_tool_call usually pass 'owner_id'
             owner_id = kwargs.get("owner_id")
             if owner_id:
                 memory.set_project_memory_file(owner_id, conversation_id)
             else:
                 return "Error: Could not determine project owner for memory."

        return memory.remember(scope, key, value)
    except Exception as e:
        return f"Error using remember tool: {e}"

def recall(scope, key, conversation_id=None, user_id=None, **kwargs):
    """
    Retrieves a fact from memory.
    Args:
        scope (str): 'user' or 'project'.
        key (str): The label/keyword to retrieve.
    """
    try:
        from memory import MemoryManager
        memory = MemoryManager(user_id=user_id)
        
        if scope == "project" and conversation_id:
             owner_id = kwargs.get("owner_id")
             if owner_id:
                 memory.set_project_memory_file(owner_id, conversation_id)
        
        val = memory.recall(scope, key)
        if val:
            return f"Recalled ({scope}): {key} = {val}"
        else:
            return f"Nothing found for '{key}' in {scope} memory."
    except Exception as e:
        return f"Error using recall tool: {e}"

def forget(scope, key, conversation_id=None, user_id=None, **kwargs):
    """
    Deletes a fact from memory.
    Args:
        scope (str): 'user' or 'project'.
        key (str): The label/keyword to forget.
    """
    try:
        from memory import MemoryManager
        memory = MemoryManager(user_id=user_id)
        
        if scope == "project" and conversation_id:
             owner_id = kwargs.get("owner_id")
             if owner_id:
                 memory.set_project_memory_file(owner_id, conversation_id)
        
        return memory.forget(scope, key)
    except Exception as e:
        return f"Error using forget tool: {e}"
# --------------------

def create_and_open_canvas(filename, content, conversation_id=None, user_id=None):
    """
    Creates a new file in the workspace and signals the frontend to open it.
    """
    write_result = write_file(filename, content, conversation_id, user_id)

    if "successfully" in write_result:
        return {
            "status": "canvas_created",
            "filename": filename,
            "message": f"Successfully created canvas '{filename}'.",
        }
    return write_result


def set_current_plan_step(step_number, step_description):
    """Informs the user about the current step of the plan being executed."""
    return {
        "status": "plan_step_update",
        "step_number": step_number,
        "step_description": step_description,
    }


def set_plan(
    steps: list, conversation_id: str, requires_approval: bool = False, **kwargs
):
    """
    Sets the agent's plan, sends it to the UI, and optionally waits for approval.
    """
    if not conversation_id:
        return "Error: conversation_id is required to set a plan."

    from utils import PLAN_APPROVALS

    PLAN_APPROVALS[conversation_id] = None  # Reset approval state

    socketio.emit(
        "plan_updated",
        {"steps": steps, "requires_approval": requires_approval},
        room=conversation_id,
    )

    if not requires_approval:
        return f"Plan with {len(steps)} steps has been set and sent to the user."

    # Wait for the user's response
    timeout = 300  # 5 minutes
    start_time = time.time()
    while time.time() - start_time < timeout:
        if PLAN_APPROVALS.get(conversation_id):
            break
        socketio.sleep(1)  # Yield control to allow other operations

    response = PLAN_APPROVALS.pop(conversation_id, "timeout")
    if response == "approve":
        return "Plan approved by the user. Proceeding with execution."
    elif response == "reject":
        return "Plan rejected by the user. Please replan based on user feedback."
    else:
        return "No response from the user within the time limit. Assuming rejection."


def update_task_status(
    step_index: int,
    status: str,
    message: str = None,
    conversation_id: str = None,
    **kwargs,
):
    """
    Updates the status of a single task in the plan.
    Status can be one of: 'in_progress', 'completed', 'failed'.
    """
    if not conversation_id:
        return "Error: conversation_id is required to update a task status."

    payload = {"step_index": step_index, "status": status, "message": message}
    socketio.emit("task_updated", payload, room=conversation_id)
    return f"Status of step {step_index} updated to {status}."


def execute_python(path, conversation_id, user_id, timeout=10, run_in_background=False, **kwargs):
    """
    Executes a Python script within the conversation's workspace.
    
    Args:
        path (str): The relative path to the Python script.
        conversation_id (str): The ID of the conversation.
        user_id (str): The ID of the user.
        timeout (int): The time in seconds to wait for the script to complete (default: 10).
        run_in_background (bool): If True, the script will continue running after the timeout
                                  if it hasn't finished, and the function will return a success message.
                                  If False (default), the script will be killed if it exceeds the timeout.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(
        os.path.abspath(workspace_path)
    ) or not file_path.endswith(".py"):
        return "Error: Access denied or not a Python file."

    try:
        # Use Popen to have more control over the process
        if run_in_background:
            # For background processes, we don't want to capture output in a way that blocks
            # But we might want to see if it crashes immediately.
            try:
                # Start the process
                process = subprocess.Popen(
                    [sys.executable, file_path],
                    cwd=workspace_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0 # Detach on Windows?
                    # On Windows, CREATE_NEW_CONSOLE might open a new window, which might be what the user wants for GUIs.
                    # But for now, let's keep it simple. If we want it "stuck on done" but not finishing,
                    # we just want to NOT kill it.
                )
                
                # Wait for the specified timeout to see if it crashes or finishes early
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                    # If we get here, the process finished within the timeout
                    output = stdout
                    if stderr:
                        output += f"\n--- ERRORS ---\n{stderr}"
                    return output
                except Exception as e:
                    if isinstance(e, subprocess.TimeoutExpired):
                         # Process is still running after timeout
                        if run_in_background:
                            # We leave it running.
                            return f"Script '{path}' started successfully and is running in the background (PID: {process.pid}). Execution timed out after {timeout} seconds but process was left running as requested."
                        else:
                            raise e
                    else:
                        raise e

            except Exception as e:
                # If communicate raised TimeoutExpired and run_in_background is False, we re-raise or handle it
                 if isinstance(e, subprocess.TimeoutExpired) and not run_in_background:
                     process.kill()
                     stdout, stderr = process.communicate()
                     output = stdout if stdout else ""
                     if stderr:
                         output += f"\n--- ERRORS ---\n{stderr}"
                     output += f"\n\nError: Execution timed out after {timeout} seconds. Process killed."
                     return output
                 raise e

        else:
            # Standard synchronous execution with timeout
            process = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workspace_path,
            )
            output = process.stdout
            if process.stderr:
                output += f"\n--- ERRORS ---\n{process.stderr}"
            return output

    except subprocess.TimeoutExpired:
        return f"Error: Execution timed out after {timeout} seconds. (Process killed)"
    except Exception as e:
        return f"Error: {str(e)}"


def pip(command, conversation_id=None, user_id=None):
    """Installs a Python package using pip."""
    try:
        command_list = [sys.executable, "-m", "pip"] + command.split() + ["--disable-pip-version-check"]
        process = subprocess.run(
            command_list, capture_output=True, text=True, timeout=120
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"


def index_workspace(conversation_id, user_id, user):
    """
    Scans the user's workspace, creates vector embeddings for each file's
    content, and stores them in a ChromaDB collection for retrieval.
    """
    if not chromadb:
        return "Error: chromadb is not installed. Please run `pip install chromadb`."

    workspace_path = get_workspace_path(conversation_id, user_id)
    if not os.path.exists(workspace_path):
        return "Workspace is empty. Nothing to index."

    try:
        # Initialize ChromaDB client and collection
        client = chromadb.Client()
        collection_name = f"workspace_{conversation_id}"
        collection = client.get_or_create_collection(name=collection_name)

        # Scan workspace and process files
        documents = []
        metadata = []
        ids = []
        file_count = 0
        for root, _, files in os.walk(workspace_path):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, workspace_path)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if content:  # Only index files with content
                            documents.append(content)
                            metadata.append({"file_path": relative_path})
                            ids.append(f"file_{file_count}")
                            file_count += 1
                except Exception as e:
                    print(f"Could not read file {file_path}: {e}")

        if not documents:
            return "No readable files found in the workspace to index."

        # Add documents to the collection (ChromaDB handles embedding)
        collection.add(documents=documents, metadatas=metadata, ids=ids)

        return f"Successfully indexed {file_count} files in the workspace."

    except Exception as e:
        return f"Error during workspace indexing: {e}"


def query_workspace(query, conversation_id, user_id, user, n_results=3):
    """
    Searches the indexed workspace for a given query and returns the most
    relevant file excerpts.
    """
    if not chromadb:
        return "Error: chromadb is not installed."

    try:
        client = chromadb.Client()
        collection_name = f"workspace_{conversation_id}"
        collection = client.get_collection(name=collection_name)

        results = collection.query(query_texts=[query], n_results=n_results)

        if not results or not results["documents"][0]:
            return "No relevant documents found in the workspace for your query."

        # Format the results for the AI
        context_str = "Relevant file excerpts from your workspace:\n\n"
        for i, doc in enumerate(results["documents"][0]):
            file_path = results["metadatas"][0][i]["file_path"]
            context_str += f"--- Excerpt from {file_path} ---\n"
            context_str += f"{doc}\n\n"

        return context_str

    except Exception as e:
        # Handle cases where the collection might not exist yet
        if "does not exist" in str(e):
            return "Workspace has not been indexed yet. Please call `index_workspace` first."
        return f"Error during workspace query: {e}"


def call_gemini_chat_stream(model, messages, system_prompt):
    """Calls Google's Gemini API via REST and yields response chunks."""
    print(f"DEBUG: Executing REST API call for model {model}")
    api_key = current_app.config.get("GOOGLE_API_KEY")
    if not api_key:
        yield "Error: GOOGLE_API_KEY not found in configuration."
        return

    # Use REST API URL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}"
    
    # Prepare contents
    contents = []
    
    # Add system prompt as a user message at start (or system instruction if supported, but simpler to prepend)
    # Gemini API supports system_instruction, let's use it properly
    payload = {
        "contents": [],
        "system_instruction": {"parts": [{"text": system_prompt}]}
    }

    import base64

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        images = msg.get("images", [])

        if role == "tool":
            role = "user"
            content = f"Tool Output:\n{content}"
        elif role == "assistant":
            role = "model"
        
        parts = []
        if content:
             parts.append({"text": content})

        for img_path in images:
            if os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as img_f:
                        img_data = base64.b64encode(img_f.read()).decode('utf-8')
                        # Detect mime type roughly
                        mime_type = "image/png"
                        if img_path.lower().endswith(".jpg") or img_path.lower().endswith(".jpeg"):
                            mime_type = "image/jpeg"
                        elif img_path.lower().endswith(".webp"):
                            mime_type = "image/webp"
                            
                        parts.append({
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": img_data
                            }
                        })
                except Exception as e:
                    print(f"Error reading image {img_path}: {e}")

        if parts:
             # Merge with previous if same role? Gemini API allows multiple turns.
             # But let's just append.
             payload["contents"].append({"role": role, "parts": parts})

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=300
        )
        response.raise_for_status()

        buffer = ""
        for line in response.iter_lines():
            if not line:
                continue
            
            # Gemini REST stream returns JSON list items separated by comma or just raw JSON objects
            # The format typically is:
            # [
            # { ... },
            # { ... }
            # ]
            # But line-by-line streaming might result in "  {" or ",".
            # Usually better to strip [ ] ,
            decoded_line = line.decode('utf-8').strip()
            if not decoded_line:
                continue

            # Handle the array wrapping [ ... ] structure
            # If our buffer is empty, we are looking for the start of a "candidate" object
            if not buffer:
                if decoded_line == '[': # Start of array
                     continue
                if decoded_line == ']': # End of array
                     continue
                if decoded_line == ',': # Separator between objects
                     continue
                if decoded_line.startswith('['): # Inline start like "[{"
                     decoded_line = decoded_line[1:].strip()
                elif decoded_line.startswith(','): # Inline separator like ",{"
                     decoded_line = decoded_line[1:].strip()

            buffer += decoded_line

            try:
                chunk_data = json.loads(buffer)
                # If we get here, we have a complete JSON object
                buffer = "" # Reset buffer for next object

                candidates = chunk_data.get("candidates", [])
                if candidates:
                    content_parts = candidates[0].get("content", {}).get("parts", [])
                    for part in content_parts:
                        if "text" in part:
                            # print(f"DEBUG: Yielding text chunk len={len(part['text'])}")
                            yield part["text"]
                
                # Check for blocking
                prompt_feedback = chunk_data.get("promptFeedback", {})
                if prompt_feedback.get("blockReason"):
                    yield f"\n[Blocked: {prompt_feedback['blockReason']}]"
                    
            except json.JSONDecodeError:
                # Incomplete JSON, continue accumulating
                continue

    except requests.exceptions.HTTPError as e:
         error_msg = f"Error calling Gemini API: {e}"
         if e.response is not None:
             try:
                 error_msg += f"\nDetails: {e.response.text}"
             except:
                 pass
         yield error_msg
    except Exception as e:
        yield f"Error calling Gemini: {str(e)}"


def call_chat_stream(model, messages, system_prompt):
    """Calls the AI chat API (Ollama or Gemini) and yields response chunks."""
    if "gemini" in model.lower():
        yield from call_gemini_chat_stream(model, messages, system_prompt)
        return

    try:
        ollama_host = current_app.config["OLLAMA_HOST"].rstrip("/")
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"

        response = requests.post(
            f"{ollama_host}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "system", "content": system_prompt}] + messages,
                "stream": True,
            },
            stream=True,
            timeout=300,
        )
        response.raise_for_status()

        for byte_line in response.iter_lines():
            if not byte_line:
                continue

            line = byte_line.decode("utf-8")
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[len("data:") :].strip()

            if not line or line == "[DONE]":
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


def ask_debugger(failed_command, error_message, user=None, user_id=None):
    """Delegates a debugging task to a specialist agent."""
    debugger_prompt = (
        f"Fix this failed command:\\n{failed_command}\\n"
        f"Error:\\n{error_message}\\nReturn ONLY the corrected JSON."
    )
    try:
        current_model = user.selected_model if user else "gemini-2.0-flash"
        messages = [{"role": "user", "content": debugger_prompt}]

        content = ""
        for chunk in call_gemini_chat_stream(current_model, messages, "You are a helpful debugger."):
             content += chunk

        json_match = re.search(r"{[\\s\\S]*}", content)
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
        "Return ONLY the raw code.\\n"
        f"Task: {task_description}\\nCode:"
    )
    try:
        current_model = user.selected_model if user else "gemini-2.0-flash"
        messages = [{"role": "user", "content": coder_prompt}]

        content = ""
        for chunk in call_gemini_chat_stream(current_model, messages, "You are an expert Python coder."):
             content += chunk

        code_match = re.search(r"```(?:\\w*\\n)?([\\s\\S]+)```", content)
        if code_match:
            return code_match.group(1).strip()
        return content.strip()
    except Exception as e:
        return f"Error calling Coder agent: {e}"



def handle_tool_call(tool_call, conversation, user):
    """Handles a tool call from the AI."""
    tool_name = tool_call.get("tool")
    raw_params = tool_call.get("parameters", {})
    file_creation_tool_used = False

    tool_map = {
        "web_search": web_search,
        "list_files": list_files,
        "read_file": read_file,
        "write_file": write_file,
        "git_clone": git_clone,
        "git_pull": git_pull,
        "git_push": git_push,
        "git_commit": git_commit,
        "git_add": git_add,
        "get_db_schema": get_db_schema,
        "run_sql_query": run_sql_query,
        "run_shell_command": run_shell_command,
        "execute_python": execute_python,
        "read_codebase": read_codebase,
        "implement_and_test_code": implement_and_test_code,
        "pip": pip,
        "index_workspace": index_workspace,
        "query_workspace": query_workspace,
        "ask_debugger": ask_debugger,
        "ask_coder": ask_coder,
        "create_and_open_canvas": create_and_open_canvas,
        "set_current_plan_step": set_current_plan_step,
        "set_plan": set_plan,
        "update_task_status": update_task_status,
        "list_core_files": list_core_files,
        "read_core_file": read_core_file,
        "read_core_file": read_core_file,
        "capture_screen": capture_screen,
        "remember": remember,
        "recall": recall,
        "forget": forget,
    }

    if tool_name in tool_map:
        if tool_name in ["create_and_open_canvas", "write_file"]:
            file_creation_tool_used = True
        tool_func = tool_map[tool_name]
        context_params = {
            "conversation_id": conversation["id"],
            "owner_id": conversation["owner_id"],
            "user_id": user.id,
            "user_data_dir": current_app.config["USER_DATA_DIR"],
            "ollama_host": current_app.config.get("OLLAMA_HOST"), # Keeping distinct for now but could be removed
            "user": user,
            "api_key": current_app.config["GOOGLE_API_KEY"],
            "cse_id": current_app.config["GOOGLE_CSE_ID"],
        }

        # If the tool operates on the workspace, it must use the owner's ID
        # to construct the correct path, not the current user's ID.
        workspace_tools = [
            "list_files",
            "read_file",
            "read_codebase",
            "write_file",
            "execute_python",
            "index_workspace",
            "query_workspace",
            "create_and_open_canvas",
            "list_directory_tree",
            "git_clone",
            "git_pull",
            "git_push",
            "git_commit",
            "git_add",
            "run_shell_command",
        ]
        if tool_name in workspace_tools:
            context_params["user_id"] = conversation["owner_id"]

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

__all__ = [
    # from submodules
    "web_search",
    "is_safe_path",
    "list_files",
    "list_directory_tree",
    "get_file_tree",
    "read_file",
    "read_codebase",
    "write_file",
    "get_workspace_path",
    "list_core_files",
    "read_core_file",
    "capture_screen",
    "git_clone",
    "git_pull",
    "git_push",
    "git_commit",
    "git_add",
    "get_db_schema",
    "run_sql_query",
    "run_shell_command",
    "implement_and_test_code",
    # from this file
    "create_and_open_canvas",
    "set_current_plan_step",
    "set_plan",
    "update_task_status",
    "execute_python",
    "pip",
    "index_workspace",
    "query_workspace",
    "ask_debugger",
    "ask_coder",
    "call_chat_stream",
    "handle_tool_call",
    "remember",
    "recall",
    "forget",
]
