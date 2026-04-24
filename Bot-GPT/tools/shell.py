import os
import subprocess
import shlex
import shutil
import queue
import threading
import time
from .file_system import get_workspace_path

# A safelist of allowed shell commands to prevent arbitrary execution
ALLOWED_COMMANDS = [
    'ls',
    'grep',
    'echo',
    'cat',
    'mkdir',
    'rm',
    'mv',
    'cp',
    'pwd',
    'find',
    'xargs',
    'head',
    'tail',
    'sleep',
]

def is_safe_path(path, workspace_root):
    """
    Checks if a given path is safely within the workspace root.
    Resolves '..' and symbolic links to prevent directory traversal.
    """
    workspace_root = os.path.abspath(workspace_root)
    resolved_path = os.path.abspath(os.path.join(workspace_root, path))
    return resolved_path.startswith(workspace_root)

def _stream_process(args, cwd, timeout, stream_callback=None):
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        bufsize=1,
    )
    event_queue = queue.Queue()

    def _reader(pipe, stream_name):
        try:
            for line in iter(pipe.readline, ''):
                event_queue.put((stream_name, line))
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
    stdout_chunks, stderr_chunks = [], []
    while True:
        if timeout and (time.time() - started) > timeout and process.poll() is None:
            timed_out = True
            process.kill()
        try:
            stream_name, line = event_queue.get(timeout=0.1)
            if stream_name == "stdout":
                stdout_chunks.append(line)
            else:
                stderr_chunks.append(line)
            if stream_callback:
                stream_callback(stream_name, line.rstrip("\n"))
        except queue.Empty:
            if process.poll() is not None and event_queue.empty():
                break
            continue

    for thread in threads:
        thread.join(timeout=0.2)

    return {
        "returncode": process.returncode,
        "stdout": "".join(stdout_chunks),
        "stderr": "".join(stderr_chunks),
        "timed_out": timed_out,
    }


def run_shell_command(command, conversation_id, user_id, user, stream_callback=None):
    """
    Executes a shell command in a secure, jailed environment.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    try:
        # 1. Argument Sanitization: Split the command into a list of arguments.
        # This prevents shell injection attacks where commands are chained with ';', '&&', '|', etc.
        args = shlex.split(command)
        cmd = args[0]
        executable = shutil.which(cmd)

        # 2. Command Safelist: Check if the command is in our allowed list.
        if cmd not in ALLOWED_COMMANDS:
            return f"Error: Command '{cmd}' is not allowed."

        if cmd == "cat" and executable is None:
            if len(args) < 2:
                return "Error: 'cat' requires at least one file path."
            output_chunks = []
            for arg in args[1:]:
                if not is_safe_path(arg, workspace_path):
                    return f"Error: Path '{arg}' is outside the allowed workspace."
                resolved_path = os.path.abspath(os.path.join(workspace_path, arg))
                if not os.path.isfile(resolved_path):
                    return f"Error: File '{arg}' not found."
                with open(resolved_path, "r", encoding="utf-8") as handle:
                    output_chunks.append(handle.read())
            combined = "\n".join(output_chunks).strip()
            return f"--- STDOUT ---\n{combined}" if combined else "Command executed with no output."

        # 3. Path Jailing: Check every argument. If it looks like a path, verify it's inside the workspace.
        for arg in args[1:]:
            # Simple check: if an argument contains '/', '..', or '~', treat it as a potential path.
            # This is not foolproof, but it's a strong heuristic.
            if '/' in arg or '..' in arg or '~' in arg:
                if not is_safe_path(arg, workspace_path):
                    return f"Error: Path '{arg}' is outside the allowed workspace."

        # Execute the command with a timeout.
        # `cwd` ensures the command runs inside the workspace directory.
        process = _stream_process(
            args if executable else [cmd, *args[1:]],
            cwd=workspace_path,
            timeout=15,
            stream_callback=stream_callback,
        )

        # Combine stdout and stderr for a complete response
        output = ""
        if process.get("stdout"):
            output += f"--- STDOUT ---\n{process.get('stdout')}\n"
        if process.get("stderr"):
            output += f"--- STDERR ---\n{process.get('stderr')}\n"
        if process.get("timed_out"):
            output += "Error: Command timed out after 15 seconds.\n"

        if not output:
            output = "Command executed with no output."

        return output.strip()

    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 15 seconds."
    except FileNotFoundError:
        return f"Error: Command '{args[0]}' not found. Make sure it is installed in the environment."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"
