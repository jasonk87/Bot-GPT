# Bot-GPT/tools/__init__.py

import os
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

from utils import get_workspace_path

# Import tool functions from sub-modules
from .web_search import web_search
from .file_system import (
    is_safe_path,
    list_files,
    list_directory_tree,
    get_file_tree,
    read_file,
    write_file,
)
from .git_integration import (
    git_clone,
    git_pull,
    git_push,
    git_commit,
    git_add,
)
from .database import get_db_schema
from .sql_query import run_sql_query


# Functions moved from the old tools.py

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


def execute_python(path, conversation_id=None, user_id=None):
    """Executes a Python script within the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(
        os.path.abspath(workspace_path)
    ) or not file_path.endswith(".py"):
        return "Error: Access denied or not a Python file."

    try:
        process = subprocess.run(
            ["python", file_path],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=workspace_path,
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
        command_list = ["pip"] + command.split() + ["--disable-pip-version-check"]
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


def ask_debugger(failed_command, error_message, user=None, user_id=None):
    """Delegates a debugging task to a specialist agent."""
    debugger_prompt = (
        f"Fix this failed command:\n{failed_command}\n"
        f"Error:\n{error_message}\nReturn ONLY the corrected JSON."
    )
    try:
        current_model = user.selected_model if user else "default_model_name"
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={
                "model": current_model,
                "messages": [{"role": "user", "content": debugger_prompt}],
                "stream": False,
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        json_match = re.search(r"{[\s\S]*}", content)
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
        current_model = user.selected_model if user else "default_model_name"
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={
                "model": current_model,
                "messages": [{"role": "user", "content": coder_prompt}],
                "stream": False,
            },
            timeout=30,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        code_match = re.search(r"```(?:\w*\n)?([\s\S]+)```", content)
        if code_match:
            return code_match.group(1).strip()
        return content.strip()
    except Exception as e:
        return f"Error calling Coder agent: {e}"


def call_ollama_chat_stream(model, messages, system_prompt):
    """Calls the Ollama chat API and yields response chunks."""
    try:
        ollama_host = current_app.config["OLLAMA_HOST"]
        response = requests.post(
            f"{ollama_host}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "system", "content": system_prompt}] + messages,
                "stream": True,
            },
            stream=True,
            timeout=120,
        )
        response.raise_for_status()

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            line = raw_line
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
        "execute_python": execute_python,
        "pip": pip,
        "index_workspace": index_workspace,
        "query_workspace": query_workspace,
        "ask_debugger": ask_debugger,
        "ask_coder": ask_coder,
        "create_and_open_canvas": create_and_open_canvas,
        "set_current_plan_step": set_current_plan_step,
        "set_plan": set_plan,
        "update_task_status": update_task_status,
    }

    if tool_name in tool_map:
        if tool_name in ["create_and_open_canvas", "write_file"]:
            file_creation_tool_used = True
        tool_func = tool_map[tool_name]
        context_params = {
            "conversation_id": conversation.id,
            "owner_id": conversation.owner_id,
            "user_id": user.id,
            "user_data_dir": current_app.config["USER_DATA_DIR"],
            "ollama_host": current_app.config["OLLAMA_HOST"],
            "user": user,
            "api_key": current_app.config["GOOGLE_API_KEY"],
            "cse_id": current_app.config["GOOGLE_CSE_ID"],
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

__all__ = [
    # from submodules
    "web_search",
    "is_safe_path",
    "list_files",
    "list_directory_tree",
    "get_file_tree",
    "read_file",
    "write_file",
    "git_clone",
    "git_pull",
    "git_push",
    "git_commit",
    "git_add",
    "get_db_schema",
    "run_sql_query",
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
    "call_ollama_chat_stream",
    "handle_tool_call",
]
