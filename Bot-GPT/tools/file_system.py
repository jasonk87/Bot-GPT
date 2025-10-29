import os
from extensions import socketio
from utils import get_workspace_path


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


def replace_in_file(path, search_content, replace_content, conversation_id=None, user_id=None):
    """
    Performs a search-and-replace operation on a file in the workspace.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return {"status": "error", "message": "Error: Could not determine workspace."}

    file_path = os.path.abspath(os.path.join(workspace_path, path))
    if not file_path.startswith(os.path.abspath(workspace_path)):
        return {"status": "error", "message": "Error: Access denied."}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        new_content = content.replace(search_content, replace_content)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # After successfully writing the file, emit an event to the room
        socketio.emit(
            "refresh_files",
            {"conversation_id": conversation_id},
            room=str(conversation_id),
        )

        return {
            "status": "file_written",
            "path": path,
            "content": new_content,
            "message": f"File '{path}' updated successfully.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}
