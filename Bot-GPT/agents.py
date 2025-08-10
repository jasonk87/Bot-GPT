import json
import re
from flask import current_app
import requests
from tools import write_file_main, read_file_main, list_directory_tree

def call_ollama_chat_sync(model, messages, system_prompt):
    """Synchronous call to the Ollama chat API."""
    ollama_host = current_app.config['OLLAMA_HOST']

    # Use the user's selected model if available, otherwise a default
    llm_model = model or "llama3.1:latest"

    response = requests.post(
        f"{ollama_host}/api/chat",
        json={
            "model": llm_model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": False  # Synchronous call
        },
        timeout=120
    )
    response.raise_for_status()
    # The response for a non-streaming chat is different
    return response.json().get("message", {}).get("content", "")

class ReActAgent:
    def __init__(self, system_prompt, tools, model=None):
        self.system_prompt = system_prompt
        self.tools = {tool.__name__: tool for tool in tools}
        self.model = model

    def execute(self, task_description, workspace_path):
        """
        Executes a task using the ReAct (Reason-Act) loop, yielding events.
        """
        messages = [{"role": "user", "content": f"Task: {task_description}"}]
        max_iterations = 10

        for i in range(max_iterations):
            yield {"type": "status", "status": f"Agent thinking... (Iteration {i+1})"}

            # --- REASON ---
            raw_response = call_ollama_chat_sync(self.model, messages, self.system_prompt)
            messages.append({"role": "assistant", "content": raw_response})

            thought_match = re.search(r'<think>([\s\S]*?)</think>', raw_response)
            thought = thought_match.group(1).strip() if thought_match else "No thought provided."
            yield {"type": "thought", "content": thought}

            tool_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', raw_response)

            if not tool_match:
                yield {"type": "status", "status": "No tool call found, finishing."}
                final_summary = raw_response.replace(thought_match.group(0), "").strip()
                yield {"type": "final_result", "summary": final_summary, "modified_files": []}
                return

            # --- ACT ---
            try:
                tool_call = json.loads(tool_match.group(1))
                tool_name = tool_call.get('tool')
                parameters = tool_call.get('parameters', {})

                # Add workspace_path to tool parameters if the tool expects it
                if tool_name in self.tools:
                    tool_func = self.tools[tool_name]
                    # Check if the tool function expects 'workspace_path'
                    import inspect
                    sig = inspect.signature(tool_func)
                    if 'workspace_path' in sig.parameters:
                        parameters['workspace_path'] = workspace_path

                yield {"type": "tool_call", "name": tool_name, "params": parameters}

                if tool_name in self.tools:
                    tool_func = self.tools[tool_name]
                    tool_result = tool_func(**parameters)

                    # Ensure result is a string for the messages list
                    if not isinstance(tool_result, str):
                        tool_result_str = json.dumps(tool_result, indent=2)
                    else:
                        tool_result_str = tool_result

                    yield {"type": "tool_result", "result": tool_result}
                    messages.append({"role": "user", "content": f"TOOL RESPONSE:\n---\n{tool_result_str}\n---"})
                else:
                    error_message = f"Error: Tool '{tool_name}' not found."
                    yield {"type": "tool_error", "error": error_message}
                    messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})

            except Exception as e:
                error_message = f"Error processing tool call: {e}"
                yield {"type": "tool_error", "error": error_message}
                messages.append({"role": "user", "content": f"TOOL RESPONSE: {error_message}"})
                # Potentially delegate to debugger agent here in a future version

        yield {"type": "final_result", "summary": "Max iterations reached.", "modified_files": []}


class CoderAgent(ReActAgent):
    def __init__(self, model=None):
        coder_system_prompt = """
You are an expert Coder Agent. Your goal is to complete the user's coding task by writing and modifying files.

**CRITICAL RULES:**
1.  **REASONING:** ALWAYS use a `<think>` block to explain your plan before calling a tool.
2.  **TOOL USE:** You have a limited set of tools. Use them to build or modify the required files.
    - `list_directory_tree(path: str)`: To see the file structure.
    - `read_file(path: str)`: To read existing file content.
    - `write_file(path: str, content: str)`: To create a new file or overwrite an existing one.
3.  **OUTPUT FORMAT:** Your response MUST be a `<think>` block followed by a single ````json ... ```` tool call.
4.  **COMPLETION:** When you believe the task is fully complete, provide your final answer *without* a tool call. Your final response should be a summary of what you did.
"""
        super().__init__(
            system_prompt=coder_system_prompt,
            tools=[write_file_main, read_file_main, list_directory_tree],
            model=model
        )

class DebuggerAgent(ReActAgent):
    def __init__(self, model=None):
        debugger_system_prompt = "You are a Debugger Agent..." # Placeholder
        super().__init__(
            system_prompt=debugger_system_prompt,
            tools=[], # Placeholder
            model=model
        )
