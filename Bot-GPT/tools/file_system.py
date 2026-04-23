import os
from flask import current_app
from extensions import socketio
from artifacts import upsert_artifact_metadata


def get_workspace_path(conversation_id, owner_id):
    """
    Constructs a path to a conversation-specific workspace.
    The path is always based on the conversation's owner.
    """
    if not owner_id or not conversation_id:
        from workspace import find_conversation_owner
        owner_id = find_conversation_owner(conversation_id)
        if not owner_id:
            return None

    path = os.path.join(
        current_app.instance_path,
        str(owner_id),
        "workspaces",
        str(conversation_id),
    )
    os.makedirs(path, exist_ok=True)
    return path


def is_safe_path(base, path, follow_symlinks=True):
    """Checks if a path is safe to access."""
    if follow_symlinks:
        return os.path.realpath(path).startswith(base)
    return os.path.abspath(path).startswith(base)


def list_files(path=".", conversation_id=None, user_id=None):
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


def list_directory_tree(path=".", conversation_id=None, user_id=None):
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
        level = root.replace(start_path, "").count(os.sep)
        indent = " " * 4 * (level)
        tree_string += f"{indent}{os.path.basename(root)}/\n"
        sub_indent = " " * 4 * (level + 1)
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
            "path": os.path.relpath(item_path, start=_original_start_path).replace(
                os.sep, "/"
            ),
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
        with open(file_path, "r", encoding="utf-8") as f:
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
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        upsert_artifact_metadata(user_id, conversation_id, path)

        # After successfully writing the file, emit an event to the room
        socketio.emit(
            "refresh_files",
            {"conversation_id": conversation_id},
            room=str(conversation_id),
        )

        return {
            "status": "file_written",
            "path": path,
            "content": content,
            "message": f"File '{path}' written successfully.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}


def read_codebase(path=".", conversation_id=None, user_id=None):
    """
    Reads all text files in a directory and returns their content concatenated.
    Useful for loading large parts of the codebase into context.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    base_path = os.path.abspath(workspace_path)
    start_path = os.path.abspath(os.path.join(base_path, path))

    if not start_path.startswith(base_path):
        return "Error: Access denied."

    if not os.path.exists(start_path):
        return f"Error: Path '{path}' does not exist."

    ignore_dirs = {
        ".git",
        "__pycache__",
        "node_modules",
        "venv",
        "env",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "instance",
        "images",
    }
    ignore_extensions = {
        ".pyc",
        ".pyo",
        ".pyd",
        ".so",
        ".dll",
        ".exe",
        ".bin",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp3",
        ".mp4",
        ".zip",
        ".tar",
        ".gz",
        ".db",
        ".sqlite",
    }

    result = []
    file_count = 0
    total_size = 0
    MAX_FILES = 200
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB safety limit

    for root, dirs, files in os.walk(start_path):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if d not in ignore_dirs]

        for file in files:
            if any(file.endswith(ext) for ext in ignore_extensions):
                continue

            file_path = os.path.join(root, file)
            # Skip if file is too large (e.g. > 1MB) to avoid choking on massive logs
            try:
                if os.path.getsize(file_path) > 1024 * 1024:
                    continue
            except OSError:
                continue

            if file_count >= MAX_FILES:
                result.append(
                    f"\n--- WARNING: File limit ({MAX_FILES}) reached. Stopping. ---\n"
                )
                return "".join(result)

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    total_size += len(content)
                    if total_size > MAX_SIZE:
                        result.append(
                            f"\n--- WARNING: Size limit ({MAX_SIZE} bytes) reached. Stopping. ---\n"
                        )
                        return "".join(result)

                    rel_path = os.path.relpath(file_path, base_path)
                    result.append(f"\n<file path=\"{rel_path}\">\n{content}\n</file>\n")
                    file_count += 1
            except Exception as e:
                result.append(f"\n--- Error reading {file}: {str(e)} ---\n")

    if not result:
        return "No readable text files found in this directory."

    return "".join(result)

def list_core_files(path="."):
    """Lists files in the application's core directory."""
    try:
        # current_app.root_path points to the Bot-GPT folder
        target_path = os.path.abspath(os.path.join(current_app.root_path, path))

        if not target_path.startswith(current_app.root_path):
             return "Error: Access denied."

        files = os.listdir(target_path)
        return "\n".join(files)
    except Exception as e:
        return f"Error: {e}"

def read_core_file(path):
    """Reads a file from the application's core directory."""
    try:
        target_path = os.path.abspath(os.path.join(current_app.root_path, path))

        if not target_path.startswith(current_app.root_path):
             return "Error: Access denied."

        with open(target_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"
