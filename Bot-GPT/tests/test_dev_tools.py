# Bot-GPT/tests/test_dev_tools.py

import pytest
from unittest.mock import MagicMock, call
from tools.dev_tools import implement_and_test_code

@pytest.fixture
def mock_tools(mocker):
    """Fixture to mock the tool dependencies."""
    mock_ask_coder = mocker.patch('tools.dev_tools.ask_coder')
    mock_write_file = mocker.patch('tools.dev_tools.write_file')
    mock_run_shell = mocker.patch('tools.dev_tools.run_shell_command')
    return mock_ask_coder, mock_write_file, mock_run_shell

def test_implement_and_test_code_success_first_try(mock_tools, app):
    """
    Tests the success scenario where the code works on the first try.
    """
    mock_ask_coder, mock_write_file, mock_run_shell = mock_tools

    # --- Mock Responses ---
    mock_ask_coder.side_effect = [
        "def new_feature():\n    return 'Hello'",  # First call: implementation
        "def test_new_feature():\n    assert new_feature() == 'Hello'",  # Second call: tests
    ]
    mock_run_shell.return_value = "1 passed in 0.01s"

    with app.app_context():
        result = implement_and_test_code(
            task_description="Create a simple greeting feature.",
            file_path="feature.py",
            test_file_path="test_feature.py",
            user=MagicMock(),
            conversation_id="123",
            user_id="456",
        )

    # --- Assertions ---
    assert "Task Completed Successfully" in result
    assert "1 passed in 0.01s" in result

    # Assert ask_coder was called correctly
    assert mock_ask_coder.call_count == 2

    # Assert write_file was called correctly
    mock_write_file.assert_has_calls([
        call("feature.py", "def new_feature():\n    return 'Hello'", conversation_id="123", user_id="456"),
        call("test_feature.py", "def test_new_feature():\n    assert new_feature() == 'Hello'", conversation_id="123", user_id="456"),
    ])

    # Assert run_shell_command was called once
    mock_run_shell.assert_called_once_with("python -m pytest test_feature.py", conversation_id="123", user_id="456")

def test_implement_and_test_code_needs_one_debug_attempt(mock_tools, app):
    """
    Tests the scenario where the code fails once, is debugged, and then passes.
    """
    mock_ask_coder, mock_write_file, mock_run_shell = mock_tools

    # --- Mock Responses ---
    mock_ask_coder.side_effect = [
        "def new_feature():\n    return 'Wrong'",  # Initial implementation
        "def test_new_feature():\n    assert new_feature() == 'Correct'",  # Test generation
        "def new_feature():\n    return 'Correct'",  # Debugged implementation
    ]
    mock_run_shell.side_effect = [
        "1 failed in 0.02s",  # First test run fails
        "1 passed in 0.01s",  # Second test run passes
    ]

    with app.app_context():
        result = implement_and_test_code(
            task_description="Create a simple greeting feature.",
            file_path="feature.py",
            test_file_path="test_feature.py",
            user=MagicMock(),
            conversation_id="123",
            user_id="456",
        )

    # --- Assertions ---
    assert "Task Completed Successfully" in result
    assert "1 passed in 0.01s" in result
    assert mock_run_shell.call_count == 2
    assert mock_ask_coder.call_count == 3 # Initial code, test, and one debug attempt

    # Check that the final, corrected code was written
    mock_write_file.assert_has_calls([
        call("feature.py", "def new_feature():\n    return 'Correct'", conversation_id="123", user_id="456"),
    ])

def test_implement_and_test_code_fails_after_max_attempts(mock_tools, app):
    """
    Tests the failure scenario where the code cannot be fixed within the max attempts.
    """
    mock_ask_coder, mock_write_file, mock_run_shell = mock_tools

    # --- Mock Responses ---
    # Coder keeps providing wrong code
    mock_ask_coder.return_value = "def new_feature():\n    return 'Wrong'"
    # Shell always returns a failure
    mock_run_shell.return_value = "1 failed in 0.03s"

    with app.app_context():
        result = implement_and_test_code(
            task_description="Create a simple greeting feature.",
            file_path="feature.py",
            test_file_path="test_feature.py",
            user=MagicMock(),
            conversation_id="123",
            user_id="456",
        )

    # --- Assertions ---
    assert "Task Failed" in result
    assert "Could not fix the code" in result
    # It should run the test MAX_DEBUG_ATTEMPTS times
    assert mock_run_shell.call_count == 5 # Corresponds to MAX_DEBUG_ATTEMPTS in dev_tools.py
