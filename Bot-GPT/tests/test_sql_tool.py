import pytest
from unittest.mock import patch, MagicMock
from tools.shell import run_shell_command
from tools import get_workspace_path
import os

def test_run_shell_command_cat_file_in_workspace(app, test_user):
    """Test that we can cat a file inside the workspace."""
    with app.app_context():
        # Create a dummy file in the workspace
        workspace_path = get_workspace_path(conversation_id=1, owner_id=test_user.id)
        test_file_path = os.path.join(workspace_path, 'test.txt')
        with open(test_file_path, 'w') as f:
            f.write('hello from workspace')

        # Use a relative path for the tool
        result = run_shell_command("cat test.txt", conversation_id=1, user=test_user, user_id=test_user.id)

    assert 'hello from workspace' in result

def test_run_shell_command_security(app, test_user):
    """Test that the shell command tool prevents unsafe commands."""
    with app.app_context():
        # Attempt to write outside the workspace
        result = run_shell_command("echo 'hello' > ../../outside.txt", conversation_id=1, user=test_user, user_id=test_user.id)
    assert "Error: Path '../../outside.txt' is outside the allowed workspace." in result
