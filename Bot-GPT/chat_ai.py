import logging
import json
import re
import time
from collections import Counter
from threading import Lock
from flask import current_app
from flask_login import current_user
from models import save_conversation

logger = logging.getLogger(__name__)


DEPTH_PROMPT_RULES = {
    "standard": (
        "Response depth: Standard. Provide a direct, well-reasoned answer with concise rationale. "
        "Do not be shallow; keep quality high while avoiding unnecessary filler."
    ),
    "deep": (
        "Response depth: Deep. Provide a structured, thorough breakdown with tradeoffs, "
        "steps, and examples where helpful."
    ),
}

NEXT_STEP_PROMPT_RULE = (
    "Always end your final user-facing response with a single line that starts with "
    "'Next step:' and gives one concrete action."
)
MODEL_ROUTER_CONFIDENCE_THRESHOLD = 0.65
DEPTH_ROUTING_METRICS = Counter()
_DEPTH_METRICS_LOCK = Lock()


def record_depth_routing(mode, source):
    with _DEPTH_METRICS_LOCK:
        DEPTH_ROUTING_METRICS["total"] += 1
        DEPTH_ROUTING_METRICS[f"mode:{mode}"] += 1
        DEPTH_ROUTING_METRICS[f"source:{source}"] += 1


def get_depth_routing_metrics():
    with _DEPTH_METRICS_LOCK:
        return dict(DEPTH_ROUTING_METRICS)


def _latest_user_message(messages):
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return (message.get("content") or "").strip()
    return ""


def _heuristic_depth_mode(messages):
    latest = _latest_user_message(messages).lower()
    if not latest:
        return "standard"

    explicit_deep_signals = (
        "deep dive",
        "in detail",
        "detailed",
        "step by step",
        "step-by-step",
        "thorough",
        "comprehensive",
        "think this through",
        "think this out",
        "pro mode",
        "dig deep",
    )
    complexity_signals = (
        "tradeoff",
        "trade-off",
        "options",
        "architecture",
        "strategy",
        "design",
        "plan",
        "roadmap",
        "root cause",
        "debug",
        "migrate",
        "refactor",
        "compare",
        "pros and cons",
        "pros/cons",
        "implementation",
        "how do we take this",
    )

    if any(signal in latest for signal in explicit_deep_signals):
        return "deep"
    if any(signal in latest for signal in complexity_signals) and len(latest) > 60:
        return "deep"
    return "standard"


def _classify_depth_with_model(model, messages, call_stream):
    latest = _latest_user_message(messages)
    if not latest or call_stream is None:
        return None

    classifier_system_prompt = (
        "You are a strict response-depth router.\n"
        "Return compact JSON only: {\"mode\":\"standard|deep\",\"confidence\":0.0-1.0}.\n"
        "- Use deep for multi-step reasoning, tradeoffs, architecture, or detailed plans.\n"
        "- Use standard for straightforward requests.\n"
        "- Set confidence high only when routing is clear."
    )
    classifier_messages = [{"role": "user", "content": latest}]
    raw = ""
    for chunk in call_stream(model, classifier_messages, classifier_system_prompt):
        raw += chunk
        if len(raw) >= 256:
            break

    parsed = None
    try:
        parsed = json.loads(raw.strip())
    except Exception:
        pass

    if isinstance(parsed, dict):
        mode = str(parsed.get("mode", "")).strip().lower()
        confidence = parsed.get("confidence")
        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = 0.0
        if mode in DEPTH_PROMPT_RULES:
            return mode, max(0.0, min(confidence_value, 1.0))

    normalized = raw.strip().lower()
    if "deep" in normalized:
        return "deep", 0.55
    if "standard" in normalized:
        return "standard", 0.55
    return None


def determine_depth_mode(messages, preference="auto", *, model=None, call_stream=None):
    normalized_preference = (preference or "auto").strip().lower()
    if normalized_preference in DEPTH_PROMPT_RULES:
        return normalized_preference, "user_preference"

    if model and call_stream:
        try:
            classified = _classify_depth_with_model(model, messages, call_stream)
            if classified:
                model_mode, confidence = classified
            else:
                model_mode, confidence = (None, 0.0)
            if model_mode in DEPTH_PROMPT_RULES and confidence >= MODEL_ROUTER_CONFIDENCE_THRESHOLD:
                return model_mode, "model_router"
            if model_mode in DEPTH_PROMPT_RULES:
                return _heuristic_depth_mode(messages), "low_confidence_fallback"
        except Exception:
            pass

    return _heuristic_depth_mode(messages), "heuristic_fallback"


def build_adaptive_depth_prompt(messages, preference="auto", *, model=None, call_stream=None):
    mode, source = determine_depth_mode(messages, preference=preference, model=model, call_stream=call_stream)
    return mode, DEPTH_PROMPT_RULES[mode], source


def ensure_next_step_line(response_content):
    content = (response_content or "").strip()
    if not content:
        return "Next step: Tell me your top priority, and I will execute it first."
    if re.search(r"(?im)^\s*next step\s*:", content):
        return content
    return f"{content}\n\nNext step: Tell me to continue, and I will execute the highest-impact action first."


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


def _extract_code_fences(content):
    fences = []
    cursor = 0
    while True:
        start = content.find("```", cursor)
        if start == -1:
            break
        language_end = content.find("\n", start + 3)
        if language_end == -1:
            break
        language = content[start + 3:language_end].strip().lower()
        end = content.find("```", language_end + 1)
        if end == -1:
            break
        fences.append((language, content[language_end + 1:end]))
        cursor = end + 3
    return fences


def _decode_json_objects(text):
    decoder = json.JSONDecoder()
    objects = []
    cursor = 0
    while True:
        start = text.find("{", cursor)
        if start == -1:
            break
        try:
            parsed, parsed_len = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        objects.append(parsed)
        cursor = start + parsed_len
    return objects


def _extract_tool_calls(full_response_content, sanitize_json):
    parsed_tool_calls = []
    seen = set()
    candidate_regions = [body for language, body in _extract_code_fences(full_response_content) if language in ("", "json")]

    if not candidate_regions:
        candidate_regions = [full_response_content]

    for region in candidate_regions:
        sanitized = sanitize_json(region)
        for parsed in _decode_json_objects(sanitized):
            if not isinstance(parsed, dict):
                continue
            if not isinstance(parsed.get("tool"), str):
                continue
            if "parameters" not in parsed:
                parsed["parameters"] = {}
            elif not isinstance(parsed.get("parameters"), dict):
                continue

            dedupe_key = json.dumps(parsed, sort_keys=True)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            parsed_tool_calls.append(parsed)

    return parsed_tool_calls


def handle_ai_response(
    data,
    *,
    initialize_chat,
    call_stream,
    handle_tool_call,
    normalize_and_prepare_tool_calls,
    execute_normalized_tool_call,
    sanitize_json,
    agent_sessions,
    update_conversation_title,
    write_file,
):
    try:
        model, system_prompt, conversation, conversation_path = initialize_chat(data)
        messages = json.loads(data.get("messages", "[]"))
        depth_preference = data.get("response_mode_preference", "auto")
        depth_mode, depth_instruction, depth_source = build_adaptive_depth_prompt(
            messages,
            preference=depth_preference,
            model=model,
            call_stream=call_stream,
        )
        record_depth_routing(depth_mode, depth_source)
        system_prompt = (
            f"{system_prompt}\n\n=== RESPONSE DEPTH MODE ===\n{depth_instruction}\n===========================\n"
            f"\n=== RESPONSE FORMAT REQUIREMENT ===\n{NEXT_STEP_PROMPT_RULE}\n===================================\n"
        )
        conversation["messages"] = messages
        save_conversation(conversation_path, conversation)
    except (ValueError, json.JSONDecodeError) as exc:
        yield {"type": "agent_error", "error": str(exc)}
        return

    yield {"type": "conversation_id", "id": conversation["id"]}
    yield {"type": "response_mode", "mode": depth_mode, "source": depth_source}
    yield {"type": "progress_update", "stage": "planning", "label": "Planning approach", "ts": time.time()}
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
            yield {"type": "progress_update", "stage": "executing", "label": "Generating response", "ts": time.time()}
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

            finalized_response_content = ensure_next_step_line(full_response_content)
            yield {"type": "progress_update", "stage": "verifying", "label": "Verifying response and next step", "ts": time.time()}
            trailing_delta = finalized_response_content[len(full_response_content):]
            full_response_content = finalized_response_content
            agent_sessions[conversation["id"]]["partial_response"] = full_response_content
            conversation["messages"].append({"role": "assistant", "content": full_response_content})
            agent_sessions[conversation["id"]]["stage"] = "thinking"
            if trailing_delta:
                yield {"type": "assistant_chunk", "content": trailing_delta}
            yield {"type": "assistant_end"}

            tool_call_candidates = _extract_tool_calls(full_response_content, sanitize_json)
            if not tool_call_candidates:
                break

            tool_calls = normalize_and_prepare_tool_calls(tool_call_candidates)
            aggregated_tool_results = []
            for tool_call in tool_calls:
                tool_call_id = f"tool_{int(time.time() * 1000)}"
                try:
                    logger.info("chat_tool_call conversation_id=%s tool=%s", conversation["id"], tool_call.tool_name)
                    yield {
                        "type": "progress_update",
                        "stage": "executing",
                        "label": f"Running tool: {tool_call.tool_name}",
                        "ts": time.time(),
                    }
                    agent_sessions[conversation["id"]]["stage"] = "tool_call"
                    agent_sessions[conversation["id"]]["tool_name"] = tool_call.tool_name
                    agent_sessions[conversation["id"]]["tool_params"] = tool_call.normalized_params
                    yield {"type": "tool_call", "tool_call_id": tool_call_id, "name": tool_call.tool_name, "params": tool_call.normalized_params}

                    execution_result = execute_normalized_tool_call(tool_call, conversation, current_user)
                    if execution_result.get("status") == "error":
                        raise ValueError(execution_result.get("error_message"))
                    tool_result = execution_result.get("result")
                    if isinstance(tool_result, dict):
                        if tool_result.get("status") == "canvas_created" or (tool_result.get("status") == "file_written" and tool_call.tool_name in ["create_and_open_canvas", "write_file"]):
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
        yield {"type": "progress_update", "stage": "finalizing", "label": "Finalizing answer", "ts": time.time()}
        yield from process_final_answer(conversation, data.get("canvas_mode", False), write_file)

    update_conversation_title(conversation, conversation_path, model)
    conversation["messages"] = [m for m in conversation["messages"] if m.get("role") in ["user", "assistant"]]
    save_conversation(conversation_path, conversation)
    try:
        from memory import MemoryManager

        memory = MemoryManager(user_id=current_user.id)
        memory.archive_conversation(conversation)
    except Exception as exc:
        current_app.logger.warning("Error archiving conversation memory: %s", exc)
    logger.info("chat_run_done conversation_id=%s title=%s", conversation["id"], conversation.get("title", "New Chat"))
    yield {"type": "done", "title": conversation.get("title", "New Chat")}
