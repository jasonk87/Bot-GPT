import subprocess
import os
from .file_system import get_workspace_path

def git_clone(repo_url, conversation_id=None, user_id=None):
    """Clones a Git repository into the conversation's workspace."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    try:
        process = subprocess.run(
            ['git', 'clone', repo_url],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=workspace_path
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"

def git_pull(repo_path, conversation_id=None, user_id=None):
    """Pulls the latest changes from a Git repository."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    repo_full_path = os.path.join(workspace_path, repo_path)
    if not os.path.isdir(repo_full_path):
        return f"Error: The path '{repo_path}' is not a valid directory."

    try:
        process = subprocess.run(
            ['git', 'pull'],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=repo_full_path
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"

def git_push(repo_path, conversation_id=None, user_id=None):
    """Pushes changes to a Git repository."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    repo_full_path = os.path.join(workspace_path, repo_path)
    if not os.path.isdir(repo_full_path):
        return f"Error: The path '{repo_path}' is not a valid directory."

    try:
        process = subprocess.run(
            ['git', 'push'],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=repo_full_path
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"

def git_commit(repo_path, message, conversation_id=None, user_id=None):
    """Commits changes to a Git repository."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    repo_full_path = os.path.join(workspace_path, repo_path)
    if not os.path.isdir(repo_full_path):
        return f"Error: The path '{repo_path}' is not a valid directory."

    try:
        process = subprocess.run(
            ['git', 'commit', '-m', message],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=repo_full_path
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"

def git_add(repo_path, files, conversation_id=None, user_id=None):
    """Adds files to the Git staging area."""
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    repo_full_path = os.path.join(workspace_path, repo_path)
    if not os.path.isdir(repo_full_path):
        return f"Error: The path '{repo_path}' is not a valid directory."

    try:
        process = subprocess.run(
            ['git', 'add'] + files,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=repo_full_path
        )
        output = process.stdout
        if process.stderr:
            output += f"\n--- ERRORS ---\n{process.stderr}"
        return output
    except Exception as e:
        return f"Error: {str(e)}"
