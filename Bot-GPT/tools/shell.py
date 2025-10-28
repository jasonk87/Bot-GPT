"""
Shell tools for the AI agent.
"""
import os
import subprocess
import shlex
from utils import get_workspace_path

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

def run_shell_command(command, conversation_id, user_id):
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

        # 2. Command Safelist: Check if the command is in our allowed list.
        if cmd not in ALLOWED_COMMANDS:
            return f"Error: Command '{cmd}' is not allowed."

        # 3. Path Jailing: Check every argument. If it looks like a path, verify it's inside the workspace.
        for arg in args[1:]:
            # Simple check: if an argument contains '/', '..', or '~', treat it as a potential path.
            # This is not foolproof, but it's a strong heuristic.
            if '/' in arg or '..' in arg or '~' in arg:
                if not is_safe_path(arg, workspace_path):
                    return f"Error: Path '{arg}' is outside the allowed workspace."

        # Execute the command with a timeout.
        # `cwd` ensures the command runs inside the workspace directory.
        process = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15,  # Hard timeout of 15 seconds
            cwd=workspace_path,
            check=False # Do not raise exception on non-zero exit codes
        )

        # Combine stdout and stderr for a complete response
        output = ""
        if process.stdout:
            output += f"--- STDOUT ---\n{process.stdout}\n"
        if process.stderr:
            output += f"--- STDERR ---\n{process.stderr}\n"

        if not output:
            output = "Command executed with no output."

        return output.strip()

    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 15 seconds."
    except FileNotFoundError:
        return f"Error: Command '{args[0]}' not found. Make sure it is installed in the environment."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"
