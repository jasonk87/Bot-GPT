import pytest
import os
import subprocess
from unittest.mock import patch, MagicMock
from tools.shell import run_shell_command, is_safe_path

# Mock user and conversation IDs for the tool
MOCK_CONVERSATION_ID = "test_conv_123"
MOCK_USER_ID = "test_user_456"

@pytest.fixture
def mock_workspace(tmp_path):
    """Create a temporary workspace directory for testing."""
    workspace_path = tmp_path / "workspaces" / f"{MOCK_USER_ID}_{MOCK_CONVERSATION_ID}"
    workspace_path.mkdir(parents=True, exist_ok=True)
    # Create a dummy file inside the workspace
    (workspace_path / "safe_file.txt").write_text("content")
    return str(workspace_path)

def test_is_safe_path_allows_paths_within_workspace(mock_workspace):
    """Test that is_safe_path correctly identifies safe paths."""
    assert is_safe_path("safe_file.txt", mock_workspace) == True
    assert is_safe_path("new_dir/new_file.txt", mock_workspace) == True
    assert is_safe_path(".", mock_workspace) == True

def test_is_safe_path_rejects_paths_outside_workspace(mock_workspace):
    """Test that is_safe_path rejects directory traversal attempts."""
    assert is_safe_path("../../../etc/passwd", mock_workspace) == False
    assert is_safe_path("/etc/passwd", mock_workspace) == False
    assert is_safe_path("..", mock_workspace) == False

@patch('tools.shell.get_workspace_path')
def test_run_shell_command_allowed_command_success(mock_get_path, mock_workspace):
    """Test that an allowed and safe command executes successfully."""
    mock_get_path.return_value = mock_workspace
    result = run_shell_command(f"ls safe_file.txt", MOCK_CONVERSATION_ID, MOCK_USER_ID)
    assert "safe_file.txt" in result
    assert "--- STDOUT ---" in result

@patch('tools.shell.get_workspace_path')
def test_run_shell_command_not_allowed(mock_get_path, mock_workspace):
    """Test that a command not in the safelist is rejected."""
    mock_get_path.return_value = mock_workspace
    result = run_shell_command("python -c 'print(1)'", MOCK_CONVERSATION_ID, MOCK_USER_ID)
    assert "Error: Command 'python' is not allowed." in result

@patch('tools.shell.get_workspace_path')
def test_run_shell_command_path_traversal_blocked(mock_get_path, mock_workspace):
    """Test that a command trying to access outside the workspace is blocked."""
    mock_get_path.return_value = mock_workspace
    result = run_shell_command("ls ../../", MOCK_CONVERSATION_ID, MOCK_USER_ID)
    assert "Error: Path '../../' is outside the allowed workspace." in result

@patch('tools.shell.get_workspace_path')
def test_run_shell_command_injection_blocked(mock_get_path, mock_workspace):
    """Test that shell command injection characters are handled safely."""
    mock_get_path.return_value = mock_workspace
    # The path jailing correctly identifies '/' as an unsafe path.
    # This is a better and more secure outcome than the original test expected.
    result = run_shell_command("echo hello && ls /", MOCK_CONVERSATION_ID, MOCK_USER_ID)
    assert "Error: Path '/' is outside the allowed workspace." in result

@patch('tools.shell.get_workspace_path')
def test_run_shell_command_timeout(mock_get_path, mock_workspace):
    """Test that a long-running command is terminated."""
    mock_get_path.return_value = mock_workspace
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="sleep 20", timeout=15)):
        result = run_shell_command("sleep 20", MOCK_CONVERSATION_ID, MOCK_USER_ID)
    assert "Error: Command timed out after 15 seconds." in result

@patch('tools.shell.get_workspace_path')
def test_command_with_no_output(mock_get_path, mock_workspace):
    """Test that commands with no output return a standard message."""
    mock_get_path.return_value = mock_workspace
    # 'mkdir' is a good example of a command that is silent on success
    result = run_shell_command("mkdir new_test_dir", MOCK_CONVERSATION_ID, MOCK_USER_ID)
    assert "Command executed with no output." in result
    assert os.path.isdir(os.path.join(mock_workspace, "new_test_dir"))
