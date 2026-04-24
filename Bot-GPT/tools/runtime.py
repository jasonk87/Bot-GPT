"""Tool runtime: dispatch and execution logic."""

import logging
import os
import sys
import subprocess
import re
import inspect
import json
import time
import queue
import threading
from dataclasses import dataclass
from typing import Any, Dict, List
from flask import current_app, has_app_context
from extensions import socketio
from os_safety import (
    OBSERVE_TOOLS,
    CAUTION_TOOLS,
    DANGEROUS_TOOLS,
    get_tool_safety_category,
    evaluate_tool_policy,
    get_or_create_approval_request,
    consume_approved_request,
    build_pending_approval_result,
)

try:
    import chromadb
except ImportError:
    chromadb = None

from .web_search import web_search
from .file_system import (
    is_safe_path,
    list_files,
    list_directory_tree,
    get_file_tree,
    read_file,
    read_codebase,
    write_file,
    get_workspace_path,
    list_core_files,
    read_core_file,
)
from utils import get_best_default_model
from .git_integration import (
    git_clone,
    git_pull,
    git_push,
    git_commit,
    git_add,
)
from .senses import capture_screen, visual_feedback_step
from .os_control import (
    move_mouse,
    click,
    type_text,
    press_key,
    open_app,
    focus_window,
    close_window,
)
from .browser_agent import (
    open_url,
    find_element_by_text,
    click_element,
    extract_visible_text,
)
from workflow_learning import (
    list_workflows as wf_list_workflows,
    start_recording_session as wf_start_recording_session,
    finalize_recording_session as wf_finalize_recording_session,
    replay_workflow as wf_replay_workflow,
    select_best_workflow as wf_select_best_workflow,
)
from visual_intelligence import (
    ocr_screen as vi_ocr_screen,
    detect_ui_elements as vi_detect_ui_elements,
    find_visual_target as vi_find_visual_target,
    verify_visual_state as vi_verify_visual_state,
)
from .optional_sql import get_db_schema, run_sql_query
from .shell import run_shell_command as base_run_shell_command
from .ai_service import call_chat_stream
from .self_healing import implement_and_test_code
from skills.github_skill import github_skill

logger = logging.getLogger(__name__)


def _runtime_config():
    if not has_app_context():
        return {}
    config = current_app.config
    if config.get("TESTING"):
        return {}
    return config


def list_workflows(user_id, **kwargs):
    return wf_list_workflows(current_app.instance_path, int(user_id))


def start_workflow_recording(name="", description="", user_id=None, **kwargs):
    return {
        "session_id": wf_start_recording_session(
            current_app.instance_path,
            int(user_id),
            name=name or None,
            description=description or "",
        )
    }


def finalize_workflow_recording(session_id, successful=True, user_id=None, **kwargs):
    workflow = wf_finalize_recording_session(
        current_app.instance_path,
        int(user_id),
        session_id,
        successful=bool(successful),
        min_steps_to_record=int(current_app.config.get("WORKFLOW_MIN_STEPS_TO_RECORD", 2)),
    )
    return {"workflow": workflow, "recorded": workflow is not None}


def run_workflow(workflow_id, user_id=None, execution_context=None, **kwargs):
    from .os_control import move_mouse, click, type_text, press_key, open_app, focus_window, close_window
    from .browser_agent import open_url, find_element_by_text, click_element
    from .senses import visual_feedback_step

    executors = {
        "move_mouse": lambda x, y, **p: move_mouse(x, y, user_id=user_id, **p),
        "click": lambda button="left", **p: click(button=button, user_id=user_id, **p),
        "type_text": lambda text, **p: type_text(text, user_id=user_id, **p),
        "press_key": lambda key, **p: press_key(key, user_id=user_id, **p),
        "open_app": lambda name, **p: open_app(name, user_id=user_id, **p),
        "focus_window": focus_window,
        "close_window": close_window,
        "open_url": lambda url, **p: open_url(url, user_id=user_id, **p),
        "find_element_by_text": lambda text, **p: find_element_by_text(text, user_id=user_id, **p),
        "click_element": lambda text, **p: click_element(text, user_id=user_id, **p),
    }

    def _verifier():
        feedback = visual_feedback_step(expected_text="", user_id=user_id)
        state = feedback.get("state") or {}
        state["url"] = None
        return state

    execution_context = dict(execution_context or {})
    user_obj = execution_context.get("user") or kwargs.get("user")
    if user_obj is None:
        class _RuntimeUser:
            def __init__(self, _user_id):
                self.id = _user_id
                self.username = None
        user_obj = _RuntimeUser(user_id)
    execution_context.setdefault("user", user_obj)

    root_policy = evaluate_tool_policy(
        "run_workflow",
        user_obj,
        current_app.config,
        execution_context=execution_context,
    )
    if not root_policy.get("allowed"):
        return {
            "status": "error",
            "error_type": "os_tool_safety_block",
            "retryable": False,
            "message": root_policy.get("reason") or "Workflow run blocked by safety policy.",
        }
    if root_policy.get("requires_approval"):
        approved = consume_approved_request(
            current_app.instance_path,
            user_id=int(user_id),
            tool_name="run_workflow",
            params={"workflow_id": workflow_id},
        )
        if not approved:
            req = get_or_create_approval_request(
                current_app.instance_path,
                user_id=int(user_id),
                tool_name="run_workflow",
                params={"workflow_id": workflow_id},
                risk_level=root_policy.get("category", "caution"),
                reason="Workflow replay requires explicit approval before executing action steps.",
                context={"source": execution_context.get("source"), "mode": execution_context.get("mode")},
            )
            return {
                "status": "pending_approval",
                "error_type": "pending_approval",
                "retryable": False,
                "approval_request": req,
                "message": "Workflow replay is pending approval.",
            }

    def _step_guard(action_type, params):
        policy = evaluate_tool_policy(
            action_type,
            execution_context.get("user"),
            current_app.config,
            execution_context=execution_context,
        )
        if not policy.get("allowed"):
            return {
                "allowed": False,
                "error_type": "os_tool_safety_block",
                "message": policy.get("reason") or "Workflow step blocked by policy.",
                "retryable": False,
            }
        return {"allowed": True}

    return wf_replay_workflow(
        current_app.instance_path,
        int(user_id),
        workflow_id,
        executors=executors,
        verifier=_verifier,
        step_guard=_step_guard,
        max_steps=int(current_app.config.get("WORKFLOW_MAX_STEPS", 25)),
    )


def find_workflow(query, user_id=None, **kwargs):
    return wf_select_best_workflow(current_app.instance_path, int(user_id), query or "")


def ocr_screen(image_path=None, conversation_id=None, user_id=None, region=None, **kwargs):
    return vi_ocr_screen(image_path=image_path, conversation_id=conversation_id, user_id=user_id, region=region)


def detect_ui_elements(ocr_result=None, image_path=None, conversation_id=None, user_id=None, **kwargs):
    if not ocr_result:
        ocr_result = ocr_screen(image_path=image_path, conversation_id=conversation_id, user_id=user_id)
    return vi_detect_ui_elements(ocr_result)


def find_visual_target(anchor, ocr_result=None, ui_elements=None, conversation_id=None, user_id=None, min_confidence=0.55, **kwargs):
    return vi_find_visual_target(
        anchor=anchor,
        ocr_result=ocr_result,
        ui_elements=ui_elements,
        conversation_id=conversation_id,
        user_id=user_id,
        min_confidence=float(min_confidence),
    )


def verify_visual_state(rule, current_state, previous_state=None, **kwargs):
    return vi_verify_visual_state(rule=rule, current_state=current_state, previous_state=previous_state)

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
                 memory.set_project_memory_file(owner_id, conversation_id, project_id=kwargs.get("project_id"))
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
                 memory.set_project_memory_file(owner_id, conversation_id, project_id=kwargs.get("project_id"))
        
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
                 memory.set_project_memory_file(owner_id, conversation_id, project_id=kwargs.get("project_id"))
        
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


def _emit_tool_stream(conversation_id: str, tool_name: str, stream_name: str, line: str):
    if not conversation_id:
        return
    socketio.emit(
        "ai_response",
        {
            "type": "tool_stream",
            "tool": tool_name,
            "stream": stream_name,
            "content": line,
            "ts": time.time(),
        },
        room=conversation_id,
    )


def _stream_process_output(process, *, timeout: int, conversation_id: str, tool_name: str):
    output_queue = queue.Queue()
    stdout_chunks = []
    stderr_chunks = []

    def _reader(pipe, stream_name):
        try:
            for line in iter(pipe.readline, ""):
                output_queue.put((stream_name, line))
        finally:
            pipe.close()

    threads = [
        threading.Thread(target=_reader, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=_reader, args=(process.stderr, "stderr"), daemon=True),
    ]
    for thread in threads:
        thread.start()

    started = time.time()
    timed_out = False
    while True:
        if timeout and (time.time() - started) > timeout and process.poll() is None:
            timed_out = True
            process.kill()
        try:
            stream_name, line = output_queue.get(timeout=0.1)
            if stream_name == "stdout":
                stdout_chunks.append(line)
            else:
                stderr_chunks.append(line)
            _emit_tool_stream(conversation_id, tool_name, stream_name, line.rstrip("\n"))
        except queue.Empty:
            if process.poll() is not None and output_queue.empty():
                break

    for thread in threads:
        thread.join(timeout=0.2)

    return {
        "stdout": "".join(stdout_chunks),
        "stderr": "".join(stderr_chunks),
        "returncode": process.returncode,
        "timed_out": timed_out,
    }


def run_shell_command(command, conversation_id, user_id, user, timeout=15, **kwargs):
    def _stream_cb(stream_name, line):
        _emit_tool_stream(conversation_id, "run_shell_command", stream_name, line)

    return base_run_shell_command(
        command,
        conversation_id=conversation_id,
        user_id=user_id,
        user=user,
        stream_callback=_stream_cb,
    )


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
        process = subprocess.Popen(
            [sys.executable, file_path],
            cwd=workspace_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_CONSOLE if (os.name == 'nt' and run_in_background) else 0,
        )

        if run_in_background:
            thread = threading.Thread(
                target=_stream_process_output,
                kwargs={
                    "process": process,
                    "timeout": timeout,
                    "conversation_id": conversation_id,
                    "tool_name": "execute_python",
                },
                daemon=True,
            )
            thread.start()
            return f"Script '{path}' started successfully in background (PID: {process.pid})."

        streamed = _stream_process_output(
            process,
            timeout=timeout,
            conversation_id=conversation_id,
            tool_name="execute_python",
        )
        output = streamed.get("stdout", "")
        if streamed.get("stderr"):
            output += f"\n--- ERRORS ---\n{streamed.get('stderr')}"
        if streamed.get("timed_out"):
            output += f"\n\nError: Execution timed out after {timeout} seconds. Process killed."
        return output or "Command executed with no output."

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


# call_gemini_chat_stream and call_chat_stream moved to ai_service.py


def ask_debugger(failed_command, error_message, user=None, user_id=None):
    """Delegates a debugging task to a specialist agent."""
    debugger_prompt = (
        f"Fix this failed command:\\n{failed_command}\\n"
        f"Error:\\n{error_message}\\nReturn ONLY the corrected JSON."
    )
    try:
        current_model = user.selected_model if user and user.selected_model else get_best_default_model()

        messages = [{"role": "user", "content": debugger_prompt}]

        content = ""
        for chunk in call_chat_stream(current_model, messages, "You are a helpful debugger."):
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
        current_model = user.selected_model if user and user.selected_model else get_best_default_model()

        messages = [{"role": "user", "content": coder_prompt}]

        content = ""
        for chunk in call_chat_stream(current_model, messages, "You are an expert Python coder."):
             content += chunk

        code_match = re.search(r"```(?:\\w*\\n)?([\\s\\S]+)```", content)
        if code_match:
            return code_match.group(1).strip()
        return content.strip()
    except Exception as e:
        return f"Error calling Coder agent: {e}"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameter_schema: Dict[str, str]
    required_fields: List[str]
    optional_fields: List[str]
    allow_unknown_fields: bool
    handler: Any
    model_visible: bool = True
    safety_category: str = "normal"


@dataclass
class NormalizedToolCall:
    tool_name: str
    raw_params: Any
    normalized_params: Dict[str, Any]
    validation_status: str
    validation_errors: List[str]
    source_metadata: Dict[str, Any]


def _build_tool_registry():
    registry = {
        "web_search": ToolDefinition("web_search", "Search the web", {"query": "str"}, ["query"], [], False, web_search),
        "list_directory_tree": ToolDefinition("list_directory_tree", "List files and directories recursively", {"path": "str"}, [], ["path"], False, list_directory_tree),
        "list_files": ToolDefinition("list_files", "List files in a directory", {"path": "str"}, [], ["path"], False, list_files),
        "read_file": ToolDefinition("read_file", "Read a file", {"path": "str"}, ["path"], [], False, read_file),
        "write_file": ToolDefinition("write_file", "Write a file", {"path": "str", "content": "str"}, ["path", "content"], [], False, write_file),
        "git_clone": ToolDefinition("git_clone", "Clone a repository", {"repo_url": "str"}, ["repo_url"], [], False, git_clone),
        "git_pull": ToolDefinition("git_pull", "Pull from git", {"repo_path": "str"}, ["repo_path"], [], False, git_pull),
        "git_push": ToolDefinition("git_push", "Push to git", {"repo_path": "str"}, ["repo_path"], [], False, git_push),
        "git_commit": ToolDefinition("git_commit", "Commit to git", {"repo_path": "str", "message": "str"}, ["repo_path", "message"], [], False, git_commit),
        "git_add": ToolDefinition("git_add", "Stage files", {"repo_path": "str", "files": "list"}, ["repo_path", "files"], [], False, git_add),
        "get_db_schema": ToolDefinition("get_db_schema", "Get DB schema", {}, [], [], False, get_db_schema),
        "run_sql_query": ToolDefinition("run_sql_query", "Run SQL", {"query": "str"}, ["query"], [], False, run_sql_query),
        "run_shell_command": ToolDefinition("run_shell_command", "Run shell command", {"command": "str"}, ["command"], [], False, run_shell_command),
        "execute_python": ToolDefinition("execute_python", "Execute python", {"path": "str", "timeout": "int", "run_in_background": "bool"}, ["path"], ["timeout", "run_in_background"], False, execute_python),
        "read_codebase": ToolDefinition("read_codebase", "Read codebase recursively", {"path": "str"}, [], ["path"], False, read_codebase),
        "implement_and_test_code": ToolDefinition("implement_and_test_code", "Self-healing coding flow", {"target_file": "str", "test_command": "str", "task_description": "str", "max_iterations": "int"}, ["target_file", "test_command", "task_description"], ["max_iterations"], False, implement_and_test_code),
        "pip": ToolDefinition("pip", "Run pip command", {"command": "str"}, ["command"], [], False, pip),
        "index_workspace": ToolDefinition("index_workspace", "Index workspace", {}, [], [], False, index_workspace),
        "query_workspace": ToolDefinition("query_workspace", "Query workspace index", {"query": "str", "n_results": "int"}, ["query"], ["n_results"], False, query_workspace),
        "ask_debugger": ToolDefinition("ask_debugger", "Delegate debugging", {"failed_command": "str", "error_message": "str"}, ["failed_command", "error_message"], [], False, ask_debugger),
        "ask_coder": ToolDefinition("ask_coder", "Delegate coding", {"task_description": "str"}, ["task_description"], [], False, ask_coder),
        "create_and_open_canvas": ToolDefinition("create_and_open_canvas", "Create canvas file", {"filename": "str", "content": "str"}, ["filename", "content"], [], False, create_and_open_canvas),
        "set_current_plan_step": ToolDefinition("set_current_plan_step", "Plan step update", {"step_number": "int", "step_description": "str"}, ["step_number", "step_description"], [], False, set_current_plan_step),
        "set_plan": ToolDefinition("set_plan", "Set plan", {"steps": "list", "requires_approval": "bool"}, ["steps"], ["requires_approval"], False, set_plan),
        "update_task_status": ToolDefinition("update_task_status", "Task status update", {"step_index": "int", "status": "str", "message": "str"}, ["step_index", "status"], ["message"], False, update_task_status),
        "list_core_files": ToolDefinition("list_core_files", "List core files", {"path": "str"}, [], ["path"], False, list_core_files),
        "read_core_file": ToolDefinition("read_core_file", "Read core file", {"path": "str"}, ["path"], [], False, read_core_file),
        "capture_screen": ToolDefinition("capture_screen", "Capture screenshot", {}, [], [], False, capture_screen),
        "move_mouse": ToolDefinition("move_mouse", "Move mouse cursor", {"x": "int", "y": "int"}, ["x", "y"], [], False, move_mouse),
        "click": ToolDefinition("click", "Click mouse button", {"button": "str"}, [], ["button"], False, click),
        "type_text": ToolDefinition("type_text", "Type text with keyboard", {"text": "str"}, ["text"], [], False, type_text),
        "press_key": ToolDefinition("press_key", "Press keyboard key", {"key": "str"}, ["key"], [], False, press_key),
        "open_app": ToolDefinition("open_app", "Open desktop application", {"name": "str"}, ["name"], [], False, open_app),
        "focus_window": ToolDefinition("focus_window", "Focus window by title", {"title": "str"}, ["title"], [], False, focus_window),
        "close_window": ToolDefinition("close_window", "Close window by title", {"title": "str"}, ["title"], [], False, close_window),
        "open_url": ToolDefinition("open_url", "Open URL in controlled browser", {"url": "str"}, ["url"], [], False, open_url),
        "find_element_by_text": ToolDefinition("find_element_by_text", "Find browser element by text", {"text": "str"}, ["text"], [], False, find_element_by_text),
        "click_element": ToolDefinition("click_element", "Click browser element by text", {"text": "str"}, ["text"], [], False, click_element),
        "extract_visible_text": ToolDefinition("extract_visible_text", "Extract visible browser text", {"max_chars": "int"}, [], ["max_chars"], False, extract_visible_text),
        "visual_feedback_step": ToolDefinition("visual_feedback_step", "Capture and verify visual result", {"expected_text": "str"}, [], ["expected_text"], False, visual_feedback_step),
        "list_workflows": ToolDefinition("list_workflows", "List learned workflows", {}, [], [], False, list_workflows),
        "start_workflow_recording": ToolDefinition("start_workflow_recording", "Start workflow recording session", {"name": "str", "description": "str"}, [], ["name", "description"], False, start_workflow_recording),
        "finalize_workflow_recording": ToolDefinition("finalize_workflow_recording", "Finalize workflow recording", {"session_id": "str", "successful": "bool"}, ["session_id"], ["successful"], False, finalize_workflow_recording),
        "run_workflow": ToolDefinition("run_workflow", "Replay a learned workflow", {"workflow_id": "str"}, ["workflow_id"], [], False, run_workflow),
        "find_workflow": ToolDefinition("find_workflow", "Find best matching workflow", {"query": "str"}, ["query"], [], False, find_workflow),
        "ocr_screen": ToolDefinition("ocr_screen", "Run OCR on screen or image", {"image_path": "str", "region": "list"}, [], ["image_path", "region"], False, ocr_screen),
        "detect_ui_elements": ToolDefinition("detect_ui_elements", "Detect UI elements from OCR", {"ocr_result": "dict", "image_path": "str"}, [], ["ocr_result", "image_path"], False, detect_ui_elements),
        "find_visual_target": ToolDefinition("find_visual_target", "Locate target using visual anchors", {"anchor": "dict", "ocr_result": "dict", "ui_elements": "dict", "min_confidence": "float"}, ["anchor"], ["ocr_result", "ui_elements", "min_confidence"], False, find_visual_target),
        "verify_visual_state": ToolDefinition("verify_visual_state", "Verify UI state changes using visual rules", {"rule": "dict", "current_state": "dict", "previous_state": "dict"}, ["rule", "current_state"], ["previous_state"], False, verify_visual_state),
        "remember": ToolDefinition("remember", "Save memory", {"scope": "str", "key": "str", "value": "str"}, ["scope", "key", "value"], [], False, remember),
        "recall": ToolDefinition("recall", "Load memory", {"scope": "str", "key": "str"}, ["scope", "key"], [], False, recall),
        "forget": ToolDefinition("forget", "Delete memory", {"scope": "str", "key": "str"}, ["scope", "key"], [], False, forget),
        "github_skill": ToolDefinition(
            "github_skill",
            "Workspace-aware GitHub/repo skill wrapper for discovery, analysis, selection, and file/commit queries",
            {"action": "str", "repo": "str", "path": "str", "base_paths": "list", "limit": "int"},
            ["action"],
            ["repo", "path", "base_paths", "limit"],
            False,
            github_skill,
        ),
    }
    for name, definition in list(registry.items()):
        registry[name] = ToolDefinition(
            name=definition.name,
            description=definition.description,
            parameter_schema=definition.parameter_schema,
            required_fields=definition.required_fields,
            optional_fields=definition.optional_fields,
            allow_unknown_fields=definition.allow_unknown_fields,
            handler=definition.handler,
            model_visible=definition.model_visible,
            safety_category=get_tool_safety_category(name),
        )
    return registry


TOOL_REGISTRY = _build_tool_registry()


def get_model_visible_tool_definitions(mode="standard", user=None, os_control_enabled=False, explicit_user_intent=False):
    visible = []
    for tool_name, definition in sorted(TOOL_REGISTRY.items(), key=lambda item: item[0]):
        if not definition.model_visible:
            continue
        if tool_name in DANGEROUS_TOOLS:
            continue
        policy = evaluate_tool_policy(
            tool_name,
            user,
            _runtime_config(),
            execution_context={
                "mode": mode,
                "os_control_enabled": os_control_enabled,
                "explicit_user_intent": explicit_user_intent,
            },
        )
        if policy.get("allowed"):
            visible.append(definition)
            continue
        if mode == "standard" and tool_name in OBSERVE_TOOLS and bool(_runtime_config().get("OS_AGENT_ENABLED", False)):
            visible.append(definition)
    return visible


def render_model_visible_tool_docs(mode="standard", user=None, os_control_enabled=False, explicit_user_intent=False):
    lines = []
    for definition in get_model_visible_tool_definitions(
        mode=mode,
        user=user,
        os_control_enabled=os_control_enabled,
        explicit_user_intent=explicit_user_intent,
    ):
        ordered_params = definition.required_fields + [
            name for name in definition.optional_fields if name not in definition.required_fields
        ]
        param_chunks = []
        for name in ordered_params:
            param_type = definition.parameter_schema.get(name, "any")
            suffix = "" if name in definition.required_fields else " = optional"
            param_chunks.append(f"{name}: {param_type}{suffix}")
        signature = ", ".join(param_chunks)
        lines.append(f"- `{definition.name}({signature})`: {definition.description}.")
    return "\n".join(lines)


def _type_matches(expected_type, value):
    expected = {
        "str": str,
        "int": int,
        "float": (int, float),
        "bool": bool,
        "list": list,
        "dict": dict,
    }.get(expected_type)
    if expected is None:
        return True
    return isinstance(value, expected)


def normalize_tool_call(candidate_tool_call, source_metadata=None):
    source_metadata = source_metadata or {}
    tool_name = candidate_tool_call.get("tool")
    raw_params = candidate_tool_call.get("parameters", {})
    validation_errors = []

    if not isinstance(tool_name, str) or not tool_name.strip():
        validation_errors.append("Invalid tool name.")
        return NormalizedToolCall("", raw_params, {}, "invalid", validation_errors, source_metadata)
    tool_name = tool_name.strip()

    definition = TOOL_REGISTRY.get(tool_name)
    if definition is None:
        validation_errors.append(f"Unknown tool '{tool_name}'.")
        return NormalizedToolCall(tool_name, raw_params, {}, "invalid", validation_errors, source_metadata)

    if not isinstance(raw_params, dict):
        validation_errors.append("Tool parameters must be an object.")
        return NormalizedToolCall(tool_name, raw_params, {}, "invalid", validation_errors, source_metadata)

    if not definition.allow_unknown_fields:
        unknown_keys = sorted(set(raw_params.keys()) - set(definition.parameter_schema.keys()))
        if unknown_keys:
            validation_errors.append(f"Unknown parameter(s): {', '.join(unknown_keys)}.")

    for required_key in definition.required_fields:
        if required_key not in raw_params:
            validation_errors.append(f"Missing required parameter '{required_key}'.")

    normalized_params = {}
    for key, value in raw_params.items():
        if key not in definition.parameter_schema:
            continue
        expected_type = definition.parameter_schema[key]
        if not _type_matches(expected_type, value):
            validation_errors.append(
                f"Invalid type for '{key}': expected {expected_type}, got {type(value).__name__}."
            )
            continue
        normalized_params[key] = value

    if validation_errors:
        return NormalizedToolCall(tool_name, raw_params, normalized_params, "invalid", validation_errors, source_metadata)
    return NormalizedToolCall(tool_name, raw_params, normalized_params, "valid", [], source_metadata)


def dedupe_normalized_tool_calls(normalized_calls):
    deduped = []
    seen = set()
    for normalized in normalized_calls:
        fingerprint = (
            normalized.tool_name,
            json.dumps(normalized.normalized_params, sort_keys=True, separators=(",", ":")),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(normalized)
    return deduped


def normalize_and_prepare_tool_calls(candidate_tool_calls):
    normalized = [
        normalize_tool_call(candidate, source_metadata={"index": idx})
        for idx, candidate in enumerate(candidate_tool_calls)
    ]
    return dedupe_normalized_tool_calls(normalized)


def execute_normalized_tool_call(normalized_tool_call, conversation, user, execution_context=None):
    execution_context = dict(execution_context or {})
    execution_context.setdefault("user", user)
    if not isinstance(normalized_tool_call, NormalizedToolCall):
        return {
            "tool_name": None,
            "status": "error",
            "result": None,
            "error_type": "protocol_error",
            "error_message": "Execution requires a NormalizedToolCall object.",
            "retryable": False,
            "validation_status": "invalid",
            "source_metadata": {},
            "file_creation_tool_used": False,
        }

    if normalized_tool_call.validation_status != "valid":
        return {
            "tool_name": normalized_tool_call.tool_name,
            "status": "error",
            "result": None,
            "error_type": "validation_error",
            "error_message": "; ".join(normalized_tool_call.validation_errors),
            "retryable": False,
            "validation_status": normalized_tool_call.validation_status,
            "source_metadata": normalized_tool_call.source_metadata,
            "file_creation_tool_used": False,
        }

    tool_name = normalized_tool_call.tool_name
    definition = TOOL_REGISTRY.get(tool_name)
    if definition is None or definition.handler is None:
        return {
            "tool_name": tool_name,
            "status": "error",
            "result": None,
            "error_type": "handler_error",
            "error_message": f"No handler registered for tool '{tool_name}'.",
            "retryable": False,
            "validation_status": normalized_tool_call.validation_status,
            "source_metadata": normalized_tool_call.source_metadata,
            "file_creation_tool_used": False,
        }

    file_creation_tool_used = tool_name in ["create_and_open_canvas", "write_file"]
    policy = evaluate_tool_policy(
        tool_name,
        user,
        current_app.config,
        execution_context=execution_context,
    )
    if not policy.get("allowed"):
        return {
            "tool_name": tool_name,
            "status": "error",
            "result": None,
            "error_type": "os_tool_safety_block",
            "error_message": policy.get("reason") or "OS tool policy blocked execution.",
            "retryable": False,
            "validation_status": normalized_tool_call.validation_status,
            "source_metadata": normalized_tool_call.source_metadata,
            "file_creation_tool_used": False,
        }

    if policy.get("requires_approval"):
        approved = consume_approved_request(
            current_app.instance_path,
            user_id=user.id,
            tool_name=tool_name,
            params=normalized_tool_call.normalized_params,
        )
        if not approved:
            approval_request = get_or_create_approval_request(
                current_app.instance_path,
                user_id=user.id,
                tool_name=tool_name,
                params=normalized_tool_call.normalized_params,
                risk_level=policy.get("category", "caution"),
                reason=policy.get("reason") or f"{policy.get('category')} tool requires explicit approval.",
                context={
                    "conversation_id": conversation.get("id"),
                    "mode": execution_context.get("mode"),
                    "source": execution_context.get("source"),
                },
            )
            pending = build_pending_approval_result(
                tool_name=tool_name,
                reason=policy.get("reason") or "Approval required before execution.",
                approval_request=approval_request,
            )
            pending.update({
                "validation_status": normalized_tool_call.validation_status,
                "source_metadata": normalized_tool_call.source_metadata,
                "file_creation_tool_used": False,
            })
            return pending

    tool_func = definition.handler
    context_params = {
        "conversation_id": conversation["id"],
        "owner_id": conversation["owner_id"],
        "project_id": conversation.get("project_id"),
        "user_id": user.id,
        "user_data_dir": current_app.config["USER_DATA_DIR"],
        "ollama_host": current_app.config.get("OLLAMA_HOST"),
        "user": user,
        "api_key": current_app.config["GOOGLE_API_KEY"],
        "cse_id": current_app.config["GOOGLE_CSE_ID"],
    }
    context_params["execution_context"] = execution_context

    workspace_tools = [
        "list_files", "read_file", "read_codebase", "write_file", "execute_python",
        "index_workspace", "query_workspace", "create_and_open_canvas", "list_directory_tree",
        "git_clone", "git_pull", "git_push", "git_commit", "git_add", "run_shell_command", "github_skill",
    ]
    if tool_name in workspace_tools:
        context_params["user_id"] = conversation["owner_id"]

    try:
        tool_params = {}
        sig = inspect.signature(tool_func)
        for param_name in sig.parameters:
            if param_name in normalized_tool_call.normalized_params:
                tool_params[param_name] = normalized_tool_call.normalized_params[param_name]
            elif param_name in context_params:
                tool_params[param_name] = context_params[param_name]

        logger.info("tool_dispatch tool=%s conversation_id=%s", tool_name, conversation.get("id"))
        result = tool_func(**tool_params)
        logger.info("tool_dispatch_done tool=%s conversation_id=%s", tool_name, conversation.get("id"))
        return {
            "tool_name": tool_name,
            "status": "success",
            "result": result,
            "error_type": None,
            "error_message": None,
            "retryable": False,
            "validation_status": normalized_tool_call.validation_status,
            "source_metadata": normalized_tool_call.source_metadata,
            "file_creation_tool_used": file_creation_tool_used,
        }
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        retryable = any(token in lowered for token in ["timeout", "temporar", "connection", "unavailable", "rate limit"])
        if any(token in lowered for token in ["permission", "denied", "access denied", "not found", "no such file"]):
            retryable = False
        return {
            "tool_name": tool_name,
            "status": "error",
            "result": None,
            "error_type": "execution_error",
            "error_message": message,
            "retryable": retryable,
            "validation_status": normalized_tool_call.validation_status,
            "source_metadata": normalized_tool_call.source_metadata,
            "file_creation_tool_used": file_creation_tool_used,
        }


def execute_tool_call_batch(normalized_tool_calls, conversation, user, execution_context=None):
    """Execute normalized tool calls in order and aggregate deterministic outcomes.

    Policy:
    - execute calls in list order
    - continue through validation/execution errors
    - preserve per-call outcomes without collapsing partial success
    - empty input returns status='empty'
    """
    if not normalized_tool_calls:
        return {
            "status": "empty",
            "policy": "continue_on_error_in_order",
            "total_calls": 0,
            "executed_calls": 0,
            "success_count": 0,
            "error_count": 0,
            "results": [],
        }

    results = []
    success_count = 0
    error_count = 0
    for normalized in normalized_tool_calls:
        outcome = execute_normalized_tool_call(normalized, conversation, user, execution_context=execution_context)
        results.append(outcome)
        if outcome.get("status") == "success":
            success_count += 1
        else:
            error_count += 1

    if error_count == 0:
        batch_status = "success"
    elif success_count == 0:
        batch_status = "error"
    else:
        batch_status = "partial_success"

    return {
        "status": batch_status,
        "policy": "continue_on_error_in_order",
        "total_calls": len(normalized_tool_calls),
        "executed_calls": len(normalized_tool_calls),
        "success_count": success_count,
        "error_count": error_count,
        "results": results,
    }


def handle_tool_call(tool_call, conversation, user):
    """Compatibility wrapper for existing call sites."""
    normalized = normalize_tool_call(tool_call)
    execution_result = execute_normalized_tool_call(normalized, conversation, user)
    if execution_result["status"] == "error":
        raise ValueError(execution_result["error_message"])
    return execution_result["result"], execution_result["file_creation_tool_used"]

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
    "move_mouse",
    "click",
    "type_text",
    "press_key",
    "open_app",
    "focus_window",
    "close_window",
    "open_url",
    "find_element_by_text",
    "click_element",
    "extract_visible_text",
    "visual_feedback_step",
    "list_workflows",
    "start_workflow_recording",
    "finalize_workflow_recording",
    "run_workflow",
    "find_workflow",
    "ocr_screen",
    "detect_ui_elements",
    "find_visual_target",
    "verify_visual_state",
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
    "github_skill",
    "call_chat_stream",
    "TOOL_REGISTRY",
    "ToolDefinition",
    "NormalizedToolCall",
    "get_model_visible_tool_definitions",
    "render_model_visible_tool_docs",
    "normalize_tool_call",
    "normalize_and_prepare_tool_calls",
    "dedupe_normalized_tool_calls",
    "execute_normalized_tool_call",
    "execute_tool_call_batch",
    "handle_tool_call",
    "remember",
    "recall",
    "forget",
]
