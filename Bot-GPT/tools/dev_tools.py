# Bot-GPT/tools/dev_tools.py

import json
from .ai_prompts import ask_coder
from .file_system import write_file
from .shell import run_shell_command

MAX_DEBUG_ATTEMPTS = 5

def implement_and_test_code(
    task_description: str,
    file_path: str,
    test_file_path: str,
    user=None,
    conversation_id=None,
    user_id=None,
):
    """
    Orchestrates the process of writing, testing, and debugging code to fulfill a given task.

    This high-level tool performs the following steps:
    1.  Generates the initial implementation code based on the task description.
    2.  Writes the code to the specified file.
    3.  Generates pytest tests for the implementation.
    4.  Writes the tests to the specified test file.
    5.  Enters a loop to run the tests and, if they fail, attempt to debug the code.
    6.  The loop continues until the tests pass or a maximum number of attempts is reached.

    Args:
        task_description (str): The detailed description of the feature to implement.
        file_path (str): The path where the implementation code should be saved.
        test_file_path (str): The path where the test code should be saved.
        user: The user object (for context).
        conversation_id (str): The ID of the current conversation.
        user_id (str): The ID of the user.

    Returns:
        str: A summary of the outcome, including success or failure and the final test results.
    """
    # Step 1 & 2: Generate and write the implementation code
    print(f"Generating implementation for: {task_description}")
    implementation_code = ask_coder(task_description, user=user, user_id=user_id)
    write_file(file_path, implementation_code, conversation_id=conversation_id, user_id=user_id)
    print(f"Implementation code written to {file_path}")

    # Step 3 & 4: Generate and write the test code
    test_generation_prompt = f"""
    You are a testing expert. Write a comprehensive pytest test suite for the following code located in `{file_path}`.
    The goal is to test the functionality described in the task: "{task_description}".
    Ensure your test covers the main functionality and any relevant edge cases.
    Return only the Python code for the test file.

    --- Code to test ---
    {implementation_code}
    """
    print("Generating tests...")
    test_code = ask_coder(test_generation_prompt, user=user, user_id=user_id)
    write_file(test_file_path, test_code, conversation_id=conversation_id, user_id=user_id)
    print(f"Tests written to {test_file_path}")

    # Step 5: Test and debug loop
    for attempt in range(MAX_DEBUG_ATTEMPTS):
        print(f"--- Debug Attempt {attempt + 1}/{MAX_DEBUG_ATTEMPTS} ---")
        test_result = run_shell_command(
            f"python -m pytest {test_file_path}",
            conversation_id=conversation_id,
            user_id=user_id,
        )

        if " passed in" in test_result and " failed in" not in test_result:
            success_message = (
                f"## Task Completed Successfully\n\n"
                f"The code has been implemented in `{file_path}` and the tests in `{test_file_path}` are passing.\n\n"
                f"**Final Test Output:**\n```\n{test_result}\n```"
            )
            print("Tests passed. Task complete.")
            return success_message

        # Tests failed, attempt to debug
        print("Tests failed. Attempting to debug...")
        debug_prompt = f"""
        The tests for your code have failed. Your task is to analyze the implementation code, the test code, and the error message, and then return a corrected version of the **implementation code only**.

        **Original Task:** {task_description}

        **Current Implementation Code (`{file_path}`):**
        ```python
        {implementation_code}
        ```

        **Test Code (`{test_file_path}`):**
        ```python
        {test_code}
        ```

        **Test Failure Output:**
        ```
        {test_result}
        ```

        Please provide the corrected implementation code. Do not provide the test code or any explanation, only the full, corrected Python code for the implementation file.
        """
        implementation_code = ask_coder(debug_prompt, user=user, user_id=user_id)
        write_file(file_path, implementation_code, conversation_id=conversation_id, user_id=user_id)
        print(f"Applied fix to {file_path}. Retrying tests...")

    failure_message = (
        f"## Task Failed\n\n"
        f"Could not fix the code after {MAX_DEBUG_ATTEMPTS} attempts.\n\n"
        f"**Final Failing Test Output:**\n```\n{test_result}\n```"
    )
    print("Max debug attempts reached. Task failed.")
    return failure_message
