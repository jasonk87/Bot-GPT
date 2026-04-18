
import os
import subprocess
import re
from .file_system import get_workspace_path, write_file

def implement_and_test_code(target_file, test_command, task_description, conversation_id=None, user_id=None, user=None, max_iterations=3):
    # Import from ai_service to avoid circular dependency
    from .ai_service import call_chat_stream
    """
    Implements code in a file and iteratively tests and fixes it until the test passes.

    Args:
        target_file: Relative path to the file to modify.
        test_command: The shell command to run tests.
        task_description: Description of what the code should do.
        max_iterations: Maximum number of fix attempts.
    """
    workspace_path = get_workspace_path(conversation_id, user_id)
    if not workspace_path:
        return "Error: Could not determine workspace."

    full_target_path = os.path.join(workspace_path, target_file)

    # 1. Initial Implementation
    # Using the same logic as ask_coder but specialized for this loop
    from utils import get_best_default_model
    current_model = user.selected_model if user and user.selected_model else get_best_default_model()


    # Check if file exists to determine if we are creating or editing
    existing_content = ""
    if os.path.exists(full_target_path):
        with open(full_target_path, 'r') as f:
            existing_content = f.read()

    initial_prompt = (
        f"Task: {task_description}\n"
        f"Target File: {target_file}\n"
    )
    if existing_content:
        initial_prompt += f"Existing Content:\n```\n{existing_content}\n```\n"
        initial_prompt += "Modify the code to satisfy the task."
    else:
        initial_prompt += "Write the full code for this file."

    initial_prompt += "\nReturn ONLY the python code block."

    # Get initial code
    code = ""
    messages = [{"role": "user", "content": initial_prompt}]
    try:
        for chunk in call_chat_stream(current_model, messages, "You are an expert Python coder."):
            code += chunk
    except Exception as e:
        return f"Error communicating with AI: {e}"

    # Extract code block
    code_match = re.search(r"```(?:\w*\n)?([\s\S]+)```", code)
    if code_match:
        code = code_match.group(1).strip()

    # Write initial code
    write_result = write_file(target_file, code, conversation_id, user_id)
    if "status" in write_result and write_result["status"] == "error":
        return f"Failed to write initial code: {write_result['message']}"

    # 2. Test-Fix Loop
    for i in range(max_iterations + 1):
        # Run test
        try:
            # We use shell=True for flexibility, but rely on the environment being jailed/safe enough for the user
            # Since this is an agent tool, we assume standard caution.
            # Ideally we'd use run_shell_command's safety, but we need the output directly here.
            process = subprocess.run(
                test_command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=workspace_path,
                timeout=30
            )
            stdout = process.stdout
            stderr = process.stderr
            returncode = process.returncode
        except Exception as e:
            return f"Error executing test command: {e}"

        if returncode == 0:
            return f"Success! Code implemented and passed tests after {i} iterations.\nOutput:\n{stdout}"

        if i == max_iterations:
            return f"Failed after {max_iterations} attempts.\nLast Output:\n{stdout}\nErrors:\n{stderr}"

        # Generate Fix
        fix_prompt = (
            f"The code in {target_file} failed the test command: '{test_command}'.\n\n"
            f"Current Code:\n```python\n{code}\n```\n\n"
            f"Test Output:\n{stdout}\nErrors:\n{stderr}\n\n"
            "Fix the code. Return ONLY the fully corrected code block."
        )

        new_code_response = ""
        messages = [{"role": "user", "content": fix_prompt}]
        try:
            for chunk in call_chat_stream(current_model, messages, "You are an expert Python debugger."):
                new_code_response += chunk
        except Exception as e:
            return f"Error getting fix from AI: {e}"

        code_match = re.search(r"```(?:\w*\n)?([\s\S]+)```", new_code_response)
        if code_match:
            code = code_match.group(1).strip()
            # Write fixed code
            write_file(target_file, code, conversation_id, user_id)
        else:
            return "AI failed to return valid code block during fix attempt."

    return "Loop finished unexpectedly."
