import logging
import json
import re
import time
from flask_login import current_user
from models import save_conversation

logger = logging.getLogger(__name__)


def process_final_answer(conversation, canvas_mode, write_file):
    if not conversation.get("messages"):
        return
    final_assistant_message = next((m for m in reversed(conversation["messages"]) if m.get("role") == "assistant"), None)
    if not final_assistant_message:
        return
    final_answer_content = final_assistant_message["content"]
    if not canvas_mode:
        yield {"type": "final_answer", "content": final_answer_content}
        return

    code_blocks = re.findall(r"```(\w*)\n([\s\S]+?)```", final_answer_content)
    if not code_blocks:
        content_to_save = re.sub(r"<think>[\s\S]*?</think>", "", final_answer_content).strip()
        file_extension = "md"
    else:
        largest_block = max(code_blocks, key=lambda item: len(item[1].split("\n")))
        language, content_to_save = largest_block[0].lower(), largest_block[1].strip()
        file_extension = {"python": "py", "javascript": "js", "html": "html", "css": "css", "json": "json", "sql": "sql", "shell": "sh", "bash": "sh"}.get(language, "txt")

    filename = f"canvas_{int(time.time())}.{file_extension}"
    write_result = write_file(path=filename, content=content_to_save, conversation_id=conversation["id"], user_id=conversation["owner_id"])
    if "successfully" in write_result.get("message", ""):
        yield {"type": "open_canvas", "filename": filename}
    else:
        yield {"type": "agent_error", "error": f"Failed to save to canvas: {write_result.get('message', '')}"}
    yield {"type": "final_answer", "content": final_answer_content}


def handle_ai_response(
    data,
    *,
    initialize_chat,
    call_stream,
    handle_tool_call,
    sanitize_json,
    agent_sessions,
    update_conversation_title,
    write_file,
):
    try:
        model, system_prompt, conversation, conversation_path = initialize_chat(data)
        messages = json.loads(data.get("messages", "[]"))
        conversation["messages"] = messages
        save_conversation(conversation_path, conversation)
    except (ValueError, json.JSONDecodeError) as exc:
        yield {"type": "agent_error", "error": str(exc)}
        return

    yield {"type": "conversation_id", "id": conversation["id"]}
    agent_mode = data.get("agent_mode", False)
    agent_sessions[conversation["id"]] = {
        "stop_requested": False,
        "running": True,
        "agent_mode": agent_mode,
        "partial_response": "",
        "stage": "thinking",
        "tool_name": None,
        "tool_params": None,
        "error": None,
    }

    max_iterations = 100 if agent_mode else 15
    tool_calls = []
    logger.info("chat_run_start conversation_id=%s agent_mode=%s max_iterations=%s", conversation["id"], agent_mode, max_iterations)
    try:
        for _ in range(max_iterations):
            if agent_sessions.get(conversation["id"], {}).get("stop_requested"):
                yield {"type": "agent_error", "error": "Agent run stopped by user."}
                break

            full_response_content = ""
            try:
                for chunk in call_stream(model, conversation["messages"], system_prompt):
                    full_response_content += chunk
                    agent_sessions[conversation["id"]]["partial_response"] = full_response_content
                    agent_sessions[conversation["id"]]["stage"] = "answering"
                    yield {"type": "assistant_chunk", "content": chunk}
            except Exception as e:
                agent_sessions[conversation["id"]]["stage"] = "error"
                agent_sessions[conversation["id"]]["error"] = str(e)
                yield {"type": "agent_error", "error": f"Could not connect to AI: {e}"}
                break

            conversation["messages"].append({"role": "assistant", "content": full_response_content})
            agent_sessions[conversation["id"]]["stage"] = "thinking"
            yield {"type": "assistant_end"}

            tool_calls = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", full_response_content)
            if not tool_calls:
                break

            aggregated_tool_results = []
            for tool_call_str in tool_calls:
                tool_call_id = f"tool_{int(time.time() * 1000)}"
                try:
                    tool_call = json.loads(sanitize_json(tool_call_str))
                    logger.info("chat_tool_call conversation_id=%s tool=%s", conversation["id"], tool_call.get("tool"))
                    agent_sessions[conversation["id"]]["stage"] = "tool_call"
                    agent_sessions[conversation["id"]]["tool_name"] = tool_call.get("tool")
                    agent_sessions[conversation["id"]]["tool_params"] = tool_call.get("parameters")
                    yield {"type": "tool_call", "tool_call_id": tool_call_id, "name": tool_call.get("tool"), "params": tool_call.get("parameters")}

                    tool_result, _ = handle_tool_call(tool_call, conversation, current_user)
                    if isinstance(tool_result, dict):
                        if tool_result.get("status") == "canvas_created" or (tool_result.get("status") == "file_written" and tool_call.get("tool") in ["create_and_open_canvas", "write_file"]):
                            yield {"type": "open_canvas", "filename": tool_result.get("path") or tool_result.get("filename")}
                        elif tool_result.get("status") == "file_written":
                            yield {"type": "file_updated", "path": tool_result.get("path"), "content": tool_result.get("content")}

                    aggregated_tool_results.append(str(tool_result))
                    agent_sessions[conversation["id"]]["stage"] = "after_tool"
                    yield {"type": "tool_result", "tool_call_id": tool_call_id, "result": tool_result}
                except Exception as e:
                    error_message = f"Error processing tool: {e}"
                    aggregated_tool_results.append(error_message)
                    agent_sessions[conversation["id"]]["stage"] = "tool_error"
                    agent_sessions[conversation["id"]]["error"] = error_message
                    yield {"type": "tool_error", "tool_call_id": tool_call_id, "error": error_message}

            conversation["messages"].append({"role": "tool", "content": "TOOL RESPONSES:\n---\n" + "\n---\n".join(aggregated_tool_results) + "\n---"})
        else:
            if agent_mode:
                yield {"type": "agent_error", "error": "Agent reached maximum iterations."}
    finally:
        agent_sessions.pop(conversation["id"], None)

    if not tool_calls:
        yield from process_final_answer(conversation, data.get("canvas_mode", False), write_file)

    update_conversation_title(conversation, conversation_path, model)
    conversation["messages"] = [m for m in conversation["messages"] if m.get("role") in ["user", "assistant"]]
    save_conversation(conversation_path, conversation)
    logger.info("chat_run_done conversation_id=%s title=%s", conversation["id"], conversation.get("title", "New Chat"))
    yield {"type": "done", "title": conversation.get("title", "New Chat")}
