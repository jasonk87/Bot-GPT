# Bot-GPT/tools/ai_prompts.py
import re
import requests
from flask import current_app


def ask_debugger(failed_command, error_message, user=None, user_id=None):
    """Delegates a debugging task to a specialist agent."""
    debugger_prompt = (
        f"Fix this failed command:\n{failed_command}\n"
        f"Error:\n{error_message}\nReturn ONLY the corrected JSON."
    )
    try:
        current_model = user.selected_model if user else "default_model_name"
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={
                "model": current_model,
                "messages": [{"role": "user", "content": debugger_prompt}],
                "stream": False,
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        json_match = re.search(r"{[\s\S]*}", content)
        if json_match:
            return f"Debugger agent suggests this fix: {json_match.group(0)}"
        else:
            return f"Debugger agent could not find a fix. It responded: {content}"
    except Exception as e:
        return f"Error calling debugger agent: {e}"


def ask_coder(task_description, user=None, user_id=None):
    """Delegates a coding task to a specialist agent."""
    coder_prompt = (
        "Write Python code for the following task. Your code should be "
        "clean, well-formatted, and include comments where necessary. "
        "Return ONLY the raw code.\n"
        f"Task: {task_description}\nCode:"
    )
    try:
        current_model = user.selected_model if user else "default_model_name"
        response = requests.post(
            f"{current_app.config['OLLAMA_HOST']}/api/chat",
            json={
                "model": current_model,
                "messages": [{"role": "user", "content": coder_prompt}],
                "stream": False,
            },
            timeout=30,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        code_match = re.search(r"```(?:\w*\n)?([\s\S]+)```", content)
        if code_match:
            return code_match.group(1).strip()
        return content.strip()
    except Exception as e:
        return f"Error calling Coder agent: {e}"
