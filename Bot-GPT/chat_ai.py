import logging
import json
import re
import time
import os
from collections import Counter
from threading import Lock
from flask import current_app
from flask_login import current_user
from models import save_conversation
from verification import (
    choose_verification_steps,
    run_verification_step,
    should_continue_repair,
    summarize_verification_results,
)
from repo_index import get_selected_repository
from context_compactor import estimate_context_usage, compact_session_history
from memory_store import update_session_memory
from prompts import inject_model_visible_tool_docs
from tools.runtime import render_model_visible_tool_docs

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


def _tool_call_fingerprint(tool_call):
    return (
        tool_call.tool_name,
        json.dumps(tool_call.normalized_params, sort_keys=True, separators=(",", ":")),
    )


def _format_tool_batch_feedback(batch_outcome, results):
    compact_results = []
    for outcome in results:
        result_payload = outcome.get("result")
        if isinstance(result_payload, dict):
            result_preview = {k: result_payload.get(k) for k in ["status", "path", "filename", "message"] if k in result_payload}
        else:
            result_preview = str(result_payload)[:240] if result_payload is not None else None
        usefulness_hint = "useful"
        if result_payload in (None, "", [], {}):
            usefulness_hint = "low_signal_empty_result"
        if outcome.get("status") != "success":
            usefulness_hint = "failed_call"
        compact_results.append({
            "tool_name": outcome.get("tool_name"),
            "status": outcome.get("status"),
            "retryable": outcome.get("retryable"),
            "validation_status": outcome.get("validation_status"),
            "error_type": outcome.get("error_type"),
            "error_message": outcome.get("error_message"),
            "result_preview": result_preview,
            "usefulness_hint": usefulness_hint,
            "source_metadata": outcome.get("source_metadata"),
        })
    return "TOOL BATCH RESULT:\n" + json.dumps({
        "batch_status": batch_outcome.get("status"),
        "policy": batch_outcome.get("policy"),
        "success_count": batch_outcome.get("success_count"),
        "error_count": batch_outcome.get("error_count"),
        "results": compact_results,
    }, indent=2, default=str)


def _initialize_intent_state(messages):
    objective = _latest_user_message(messages) or "Complete the user's request."
    return {
        "objective": objective,
        "current_focus": "Gather the minimum evidence required to answer.",
        "completed_items": [],
        "blocked_items": [],
        "next_step_hint": "Use the smallest sufficient next tool action.",
        "ready_to_answer": False,
    }


def _render_intent_state(intent_state):
    return (
        "=== INTENT CONTINUITY STATE ===\n"
        + json.dumps(intent_state, indent=2, default=str)
        + "\nUse this state to maintain continuity across loops.\n"
        "===============================\n"
    )


def _render_verification_state(verification_state):
    if not verification_state:
        return ""
    pending = verification_state.get("pending_failure")
    if not pending:
        return ""
    return (
        "\n=== VERIFICATION LOOP STATE ===\n"
        f"attempt: {verification_state.get('attempts', 0)} / {verification_state.get('max_attempts', 0)}\n"
        f"failed_step: {pending.get('step_type')} -> {pending.get('command')}\n"
        f"classification: {pending.get('classification')}\n"
        "instruction: apply the smallest patch for this failure, then rerun verification.\n"
        "===============================\n"
    )


def _render_repo_context(owner_id):
    repo = get_selected_repository(owner_id)
    if not repo:
        return ""
    entry_points = repo.get("entry_points") or []
    return (
        "\n=== REPOSITORY CONTEXT ===\n"
        f"name: {repo.get('name')}\n"
        f"path: {repo.get('path')}\n"
        f"primary_languages: {', '.join(repo.get('primary_languages') or [])}\n"
        f"preferred_entry_point: {repo.get('preferred_preview_target')}\n"
        f"detected_entry_points: {', '.join(entry_points[:5])}\n"
        "When coding, prefer scoped patches in this selected repository.\n"
        "==========================\n"
    )


def _render_scratchpad(scratchpad):
    notes = scratchpad.get("notes", []) if isinstance(scratchpad, dict) else []
    if not notes:
        return ""
    return (
        "\n=== WORKING SCRATCHPAD (RUN-LOCAL) ===\n"
        + "\n".join(f"- {note}" for note in notes[-6:])
        + "\n======================================\n"
    )


def _update_intent_state(intent_state, tool_calls, results, batch_outcome):
    for tool_call, result in zip(tool_calls, results):
        descriptor = f"{tool_call.tool_name} {tool_call.normalized_params}"
        if result.get("status") == "success":
            completion_note = f"Completed: {descriptor}"
            if completion_note not in intent_state["completed_items"]:
                intent_state["completed_items"].append(completion_note)
        elif result.get("retryable") is False:
            block_note = f"Blocked: {descriptor} -> {result.get('error_type')}"
            if block_note not in intent_state["blocked_items"]:
                intent_state["blocked_items"].append(block_note)

    batch_status = batch_outcome.get("status")
    if batch_status == "success":
        intent_state["current_focus"] = "Synthesize successful results and determine if answer is ready."
        intent_state["next_step_hint"] = "Prefer answering if evidence is sufficient; otherwise run one targeted follow-up."
    elif batch_status == "partial_success":
        intent_state["current_focus"] = "Continue from successful branches; recover only unresolved failures."
        intent_state["next_step_hint"] = "Use successful outputs first, then selectively recover failed critical branches."
    elif batch_status == "error":
        intent_state["current_focus"] = "Pivot strategy away from blocked/non-productive calls."
        intent_state["next_step_hint"] = "Change parameters/tool choice or ask a clarifying question."
    elif batch_status == "empty":
        intent_state["next_step_hint"] = "No executable calls produced; either clarify, pivot, or answer with current evidence."

    intent_state["ready_to_answer"] = (
        len(intent_state["completed_items"]) > 0
        and batch_status in ("success", "partial_success")
    )
    return intent_state


def _mode_profile(depth_mode, agent_mode):
    if agent_mode:
        return {
            "mode": "agent",
            "max_iterations": 100,
            "tool_batch_budget": None,
            "branch_limit": 5,
        }
    if depth_mode == "deep":
        return {
            "mode": "deep",
            "max_iterations": 30,
            "tool_batch_budget": 5,
            "branch_limit": 3,
        }
    return {
        "mode": "standard",
        "max_iterations": 12,
        "tool_batch_budget": 2,
        "branch_limit": 1,
    }


def _collect_changed_artifacts(tool_results):
    changed = []
    for result in tool_results or []:
        payload = result.get("result")
        if not isinstance(payload, dict):
            continue
        path = payload.get("path") or payload.get("filename")
        if isinstance(path, str) and path.strip():
            changed.append(path.strip())
    return sorted(set(changed))


def _run_verification_loop(changed_paths, latest_user_message, conversation):
    steps = choose_verification_steps(changed_paths, latest_user_message)
    if not steps:
        return {"status": "not_applicable", "results": [], "summary": "No verification steps selected.", "pending_failure": None}

    workspace_path = os.path.join(
        current_app.instance_path,
        str(conversation["owner_id"]),
        "workspaces",
        str(conversation["id"]),
    )
    if not os.path.isdir(workspace_path):
        return {
            "status": "blocked",
            "results": [],
            "summary": "Verification blocked: workspace path is unavailable.",
            "pending_failure": {"classification": "command_error", "step_type": "verification", "command": "workspace_lookup"},
        }

    results = []
    first_failure = None
    for step in steps:
        outcome = run_verification_step(step, workspace_path)
        results.append(outcome)
        if not outcome.get("success") and first_failure is None:
            first_failure = outcome

    status = "passed" if first_failure is None else "failed"
    return {
        "status": status,
        "results": results,
        "summary": summarize_verification_results(results),
        "pending_failure": first_failure,
    }


def _render_mode_guidance(profile):
    if profile["mode"] == "standard":
        return (
            "=== MODE DISCIPLINE ===\n"
            "Mode: standard\n"
            "- Find the shortest credible path to a good answer.\n"
            "- Single-path reasoning only; avoid multi-branch exploration.\n"
            "- Keep tool usage minimal (0-2 batches typical).\n"
            "- Exit early and answer once evidence is sufficient.\n"
            "========================\n"
        )
    if profile["mode"] == "deep":
        return (
            "=== MODE DISCIPLINE ===\n"
            "Mode: deep\n"
            "- Use structured, thorough reasoning with controlled branching.\n"
            "- Allow up to 2-3 distinct hypotheses when justified.\n"
            "- Moderate tool budget; escalate when narrower attempts are insufficient.\n"
            "========================\n"
        )
    return (
        "=== MODE DISCIPLINE ===\n"
        "Mode: agent\n"
        "- Persistent autonomous execution toward task completion.\n"
        "- Maintain progress and continuity across multi-step loops.\n"
        "- Explore broadly only when needed; avoid redundant branches.\n"
        "========================\n"
    )


def handle_ai_response(
    data,
    *,
    initialize_chat,
    call_stream,
    handle_tool_call,
    normalize_and_prepare_tool_calls,
    execute_normalized_tool_call,
    execute_tool_call_batch,
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
    os_control_enabled = bool(data.get("os_control_enabled", False))
    explicit_user_intent = bool(data.get("explicit_os_intent", False))
    agent_sessions[conversation["id"]] = {
        "stop_requested": False,
        "running": True,
        "agent_mode": agent_mode,
        "partial_response": "",
        "stage": "thinking",
        "tool_name": None,
        "tool_params": None,
        "error": None,
        "os_control_enabled": os_control_enabled,
    }

    profile = _mode_profile(depth_mode, agent_mode)
    filtered_tool_docs = render_model_visible_tool_docs(
        mode=profile["mode"],
        user=current_user,
        os_control_enabled=os_control_enabled,
        explicit_user_intent=explicit_user_intent,
    )
    system_prompt = inject_model_visible_tool_docs(system_prompt, filtered_tool_docs)
    max_iterations = profile["max_iterations"]
    tool_calls = []
    intent_state = _initialize_intent_state(messages)
    blocked_tool_fingerprints = set()
    last_success_state_by_fingerprint = {}
    workspace_state_version = 0
    executed_tool_batches = 0
    verification_state = {
        "pending_failure": None,
        "attempts": 0,
        "max_attempts": 3,
        "last_summary": "",
    }
    scratchpad = {"notes": []}
    mutating_tools = {
        "write_file",
        "create_and_open_canvas",
        "run_shell_command",
        "execute_python",
        "implement_and_test_code",
        "git_add",
        "git_commit",
        "git_pull",
        "git_push",
    }
    logger.info("chat_run_start conversation_id=%s agent_mode=%s max_iterations=%s", conversation["id"], agent_mode, max_iterations)
    try:
        for _ in range(max_iterations):
            if agent_sessions.get(conversation["id"], {}).get("stop_requested"):
                yield {"type": "agent_error", "error": "Agent run stopped by user."}
                break

            full_response_content = ""
            yield {"type": "progress_update", "stage": "executing", "label": "Generating response", "ts": time.time()}
            try:
                iteration_prompt = (
                    f"{system_prompt}\n{_render_mode_guidance(profile)}\n"
                    f"{_render_intent_state(intent_state)}{_render_verification_state(verification_state)}"
                    f"{_render_repo_context(conversation['owner_id'])}"
                    f"{_render_scratchpad(scratchpad)}"
                )
                for chunk in call_stream(model, conversation["messages"], iteration_prompt):
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

            context_usage = estimate_context_usage(conversation["messages"])
            if context_usage >= 0.75:
                compacted = compact_session_history(conversation["messages"], keep_recent=8)
                if compacted.get("summary"):
                    conversation["messages"] = compacted["trimmed_messages"]
                    conversation["messages"].insert(0, {
                        "role": "system",
                        "content": f"Session memory summary: {compacted['summary']}",
                    })
                    update_session_memory(
                        current_user.id,
                        conversation["id"],
                        compacted["summary"],
                        compacted.get("key_notes", []),
                    )
                    scratchpad["notes"].append(f"Compacted context at {int(context_usage * 100)}% usage")

            tool_call_candidates = _extract_tool_calls(full_response_content, sanitize_json)
            if not tool_call_candidates:
                if should_continue_repair(
                    verification_state.get("pending_failure"),
                    verification_state.get("attempts", 0),
                    verification_state.get("max_attempts", 0),
                ):
                    conversation["messages"].append({
                        "role": "tool",
                        "content": (
                            "VERIFICATION LOOP NOTICE:\n"
                            "A verification failure is still unresolved. Apply the smallest patch and rerun verification."
                        ),
                    })
                    continue
                if verification_state.get("pending_failure"):
                    pending = verification_state["pending_failure"]
                    yield {
                        "type": "agent_error",
                        "error": (
                            "Verification blocked completion after maximum safe repair attempts. "
                            f"Last failure classification: {pending.get('classification')}."
                        ),
                    }
                break

            if profile["tool_batch_budget"] is not None and executed_tool_batches >= profile["tool_batch_budget"]:
                conversation["messages"].append({
                    "role": "tool",
                    "content": "TOOL BUDGET NOTICE:\nReached mode tool-batch budget; answer with current evidence unless user requests deeper exploration.",
                })
                break

            tool_calls = normalize_and_prepare_tool_calls(tool_call_candidates)
            if len(tool_calls) > profile["branch_limit"]:
                tool_calls = tool_calls[: profile["branch_limit"]]
            guard_outcomes_by_fp = {}
            executable_calls = []
            for tool_call in tool_calls:
                fingerprint = _tool_call_fingerprint(tool_call)
                if fingerprint in blocked_tool_fingerprints:
                    guard_outcomes_by_fp[fingerprint] = {
                        "tool_name": tool_call.tool_name,
                        "status": "error",
                        "result": None,
                        "error_type": "loop_guard_non_retryable_repeat",
                        "error_message": "Repeated identical call after non-retryable/validation failure. Change parameters or approach.",
                        "retryable": False,
                        "validation_status": tool_call.validation_status,
                        "source_metadata": tool_call.source_metadata,
                        "file_creation_tool_used": False,
                    }
                elif last_success_state_by_fingerprint.get(fingerprint) == workspace_state_version:
                    guard_outcomes_by_fp[fingerprint] = {
                        "tool_name": tool_call.tool_name,
                        "status": "error",
                        "result": None,
                        "error_type": "redundant_call_same_context",
                        "error_message": "Repeated identical call in unchanged context. Escalate or choose a different tool.",
                        "retryable": False,
                        "validation_status": tool_call.validation_status,
                        "source_metadata": tool_call.source_metadata,
                        "file_creation_tool_used": False,
                    }
                else:
                    executable_calls.append(tool_call)

            batch_outcome = execute_tool_call_batch(
                executable_calls,
                conversation,
                current_user,
                execution_context={
                    "mode": profile["mode"],
                    "os_control_enabled": os_control_enabled,
                    "explicit_user_intent": explicit_user_intent,
                    "source": "chat",
                },
            )
            execution_results_by_fp = {
                _tool_call_fingerprint(call): outcome
                for call, outcome in zip(executable_calls, batch_outcome.get("results", []))
            }
            aggregated_tool_results = []
            for tool_call in tool_calls:
                fingerprint = _tool_call_fingerprint(tool_call)
                execution_result = guard_outcomes_by_fp.get(fingerprint) or execution_results_by_fp.get(fingerprint)
                if not execution_result:
                    execution_result = {
                        "tool_name": tool_call.tool_name,
                        "status": "error",
                        "result": None,
                        "error_type": "runtime_mismatch",
                        "error_message": "No execution outcome available.",
                        "retryable": False,
                        "validation_status": tool_call.validation_status,
                        "source_metadata": tool_call.source_metadata,
                        "file_creation_tool_used": False,
                    }
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
                    if execution_result.get("status") == "success":
                        tool_result = execution_result.get("result")
                        if isinstance(tool_result, dict):
                            if tool_result.get("status") == "canvas_created" or (tool_result.get("status") == "file_written" and tool_call.tool_name in ["create_and_open_canvas", "write_file"]):
                                yield {"type": "open_canvas", "filename": tool_result.get("path") or tool_result.get("filename")}
                            elif tool_result.get("status") == "file_written":
                                yield {"type": "file_updated", "path": tool_result.get("path"), "content": tool_result.get("content")}
                            elif tool_result.get("status") == "repo_selected" and tool_result.get("entry_point"):
                                yield {"type": "open_canvas", "filename": tool_result.get("entry_point")}

                        aggregated_tool_results.append(execution_result)
                        scratchpad["notes"].append(f"Tool success: {tool_call.tool_name}")
                        last_success_state_by_fingerprint[fingerprint] = workspace_state_version
                        if tool_call.tool_name in mutating_tools:
                            workspace_state_version += 1
                        agent_sessions[conversation["id"]]["stage"] = "after_tool"
                        yield {"type": "tool_result", "tool_call_id": tool_call_id, "result": tool_result, "meta": execution_result}
                    else:
                        error_message = (
                            f"[{execution_result.get('error_type')}] {execution_result.get('error_message')} "
                            f"(retryable={execution_result.get('retryable')})"
                        )
                        if (
                            execution_result.get("validation_status") != "valid"
                            or execution_result.get("retryable") is False
                        ):
                            blocked_tool_fingerprints.add(fingerprint)
                        aggregated_tool_results.append(execution_result)
                        scratchpad["notes"].append(
                            f"Tool failure ({execution_result.get('error_type')}): {tool_call.tool_name}"
                        )
                        agent_sessions[conversation["id"]]["stage"] = "tool_error"
                        agent_sessions[conversation["id"]]["error"] = error_message
                        yield {"type": "tool_error", "tool_call_id": tool_call_id, "error": error_message, "meta": execution_result}
                except Exception as e:
                    fallback_result = {
                        "tool_name": tool_call.tool_name,
                        "status": "error",
                        "result": None,
                        "error_type": "chat_runtime_error",
                        "error_message": str(e),
                        "retryable": False,
                        "validation_status": "unknown",
                        "source_metadata": tool_call.source_metadata,
                    }
                    aggregated_tool_results.append(fallback_result)
                    agent_sessions[conversation["id"]]["stage"] = "tool_error"
                    agent_sessions[conversation["id"]]["error"] = str(e)
                    yield {"type": "tool_error", "tool_call_id": tool_call_id, "error": str(e)}

            conversation["messages"].append({
                "role": "tool",
                "content": _format_tool_batch_feedback(batch_outcome, aggregated_tool_results),
            })
            changed_paths = _collect_changed_artifacts(aggregated_tool_results)
            ran_mutating = any(
                result.get("status") == "success" and call.tool_name in mutating_tools
                for call, result in zip(tool_calls, aggregated_tool_results)
            )
            if ran_mutating and changed_paths:
                yield {
                    "type": "progress_update",
                    "stage": "verifying",
                    "label": "Running verification loop",
                    "ts": time.time(),
                }
                verification_report = _run_verification_loop(
                    changed_paths,
                    _latest_user_message(messages),
                    conversation,
                )
                verification_state["last_summary"] = verification_report.get("summary", "")
                if verification_report.get("status") == "failed":
                    verification_state["pending_failure"] = verification_report.get("pending_failure")
                    verification_state["attempts"] += 1
                    failure = verification_state["pending_failure"] or {}
                    yield {
                        "type": "activity_update",
                        "stage": "analyzing",
                        "focus": "verification_failure",
                        "last_action": f"Verification failed: {failure.get('classification')}",
                        "active_tool": "verification",
                    }
                    scratchpad["notes"].append(
                        f"Verification failed: {failure.get('classification')} ({failure.get('command')})"
                    )
                elif verification_report.get("status") == "passed":
                    verification_state["pending_failure"] = None
                    verification_state["attempts"] = 0
                    yield {
                        "type": "activity_update",
                        "stage": "analyzing",
                        "focus": "verification_passed",
                        "last_action": "Verification passed",
                        "active_tool": "verification",
                    }
                    scratchpad["notes"].append("Verification passed")
                conversation["messages"].append({
                    "role": "tool",
                    "content": verification_report.get("summary", "Verification completed."),
                })
            intent_state = _update_intent_state(intent_state, tool_calls, aggregated_tool_results, batch_outcome)
            yield {
                "type": "activity_update",
                "stage": "analyzing",
                "focus": intent_state.get("current_focus"),
                "last_action": intent_state.get("next_step_hint"),
                "active_tool": None,
            }
            executed_tool_batches += 1
            if (
                profile["mode"] == "standard"
                and intent_state.get("ready_to_answer")
                and batch_outcome.get("status") in ("success", "partial_success")
                and verification_state.get("pending_failure") is None
            ):
                break
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
