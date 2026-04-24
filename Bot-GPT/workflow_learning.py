import json
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover
    class FileLock:  # type: ignore[override]
        def __init__(self, _path):
            self._path = _path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

from memory_store import upsert_fact


def _workflow_path(instance_path: str, user_id: int) -> str:
    return os.path.join(instance_path, str(user_id), "workflows.json")


def _read_json(path: str, default):
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, FileNotFoundError):
            return default


def _write_json(path: str, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = FileLock(f"{path}.lock")
    with lock:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


def list_workflows(instance_path: str, user_id: int) -> List[Dict[str, object]]:
    data = _read_json(_workflow_path(instance_path, user_id), {"workflows": [], "recording_sessions": {}})
    return list(data.get("workflows", []))


def get_workflow(instance_path: str, user_id: int, workflow_id: str) -> Optional[Dict[str, object]]:
    for workflow in list_workflows(instance_path, user_id):
        if workflow.get("workflow_id") == workflow_id:
            return workflow
    return None


def delete_workflow(instance_path: str, user_id: int, workflow_id: str) -> bool:
    data = _read_json(_workflow_path(instance_path, user_id), {"workflows": [], "recording_sessions": {}})
    workflows = data.get("workflows", [])
    filtered = [wf for wf in workflows if wf.get("workflow_id") != workflow_id]
    if len(filtered) == len(workflows):
        return False
    data["workflows"] = filtered
    _write_json(_workflow_path(instance_path, user_id), data)
    return True


def _load_data(instance_path: str, user_id: int) -> Dict[str, object]:
    return _read_json(_workflow_path(instance_path, user_id), {"workflows": [], "recording_sessions": {}})


def _save_data(instance_path: str, user_id: int, payload: Dict[str, object]) -> None:
    _write_json(_workflow_path(instance_path, user_id), payload)


def start_recording_session(
    instance_path: str,
    user_id: int,
    *,
    name: Optional[str] = None,
    description: str = "",
    project_id: Optional[str] = None,
    app_site: Optional[str] = None,
) -> str:
    data = _load_data(instance_path, user_id)
    session_id = uuid.uuid4().hex
    data.setdefault("recording_sessions", {})[session_id] = {
        "session_id": session_id,
        "name": name or f"Workflow {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "description": description,
        "project_id": project_id,
        "app_site": app_site,
        "created_at": time.time(),
        "steps": [],
    }
    _save_data(instance_path, user_id, data)
    return session_id


def record_workflow_step(
    instance_path: str,
    user_id: int,
    session_id: str,
    *,
    action_type: str,
    parameters: Dict[str, object],
    context: Optional[Dict[str, object]] = None,
    verification_rule: Optional[Dict[str, object]] = None,
    fallback_hints: Optional[List[Dict[str, object]]] = None,
    visual_anchor: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    data = _load_data(instance_path, user_id)
    session = data.get("recording_sessions", {}).get(session_id)
    if not session:
        raise KeyError("recording session not found")

    step = {
        "step_id": uuid.uuid4().hex,
        "action_type": action_type,
        "parameters": parameters,
        "context": context or {},
        "verification_rule": verification_rule or {},
        "fallback_hints": fallback_hints or [],
        "visual_anchor": visual_anchor or {},
    }
    session.setdefault("steps", []).append(step)
    _save_data(instance_path, user_id, data)
    return step


def finalize_recording_session(
    instance_path: str,
    user_id: int,
    session_id: str,
    *,
    successful: bool,
    min_steps_to_record: int = 2,
) -> Optional[Dict[str, object]]:
    data = _load_data(instance_path, user_id)
    session = data.get("recording_sessions", {}).get(session_id)
    if not session:
        return None

    steps = session.get("steps", [])
    if not successful or len(steps) < int(min_steps_to_record):
        data["recording_sessions"].pop(session_id, None)
        _save_data(instance_path, user_id, data)
        return None

    workflow = {
        "workflow_id": uuid.uuid4().hex,
        "user_id": int(user_id),
        "name": session.get("name") or "Recorded workflow",
        "description": session.get("description") or "",
        "created_at": time.time(),
        "last_used": None,
        "success_rate": 1.0,
        "run_count": 0,
        "success_count": 0,
        "project_id": session.get("project_id"),
        "app_site": session.get("app_site"),
        "steps": steps,
    }
    data.setdefault("workflows", []).append(workflow)
    data["recording_sessions"].pop(session_id, None)
    _save_data(instance_path, user_id, data)
    return workflow


def select_best_workflow(instance_path: str, user_id: int, query: str) -> Optional[Dict[str, object]]:
    query_tokens = {token for token in (query or "").lower().split() if token}
    best: Optional[Tuple[float, Dict[str, object]]] = None

    for workflow in list_workflows(instance_path, user_id):
        name_tokens = set((workflow.get("name") or "").lower().split())
        desc_tokens = set((workflow.get("description") or "").lower().split())
        overlap = len(query_tokens & (name_tokens | desc_tokens))
        score = overlap + float(workflow.get("success_rate") or 0.0) + min(1.0, float(workflow.get("run_count") or 0) / 10)
        if best is None or score > best[0]:
            best = (score, workflow)

    if not best or best[0] <= 0:
        return None
    return best[1]


def _verify_step(step: Dict[str, object], observed_state: Dict[str, object]) -> bool:
    from visual_intelligence import verify_visual_state as vi_verify_visual_state

    rule = step.get("verification_rule") or {}
    result = vi_verify_visual_state(rule=rule, current_state=observed_state)
    return result.get("status") == "success"


def _resolve_parameters_with_anchor(step: Dict[str, object], observed_state: Dict[str, object], min_confidence: float = 0.55) -> Tuple[Dict[str, object], Dict[str, object]]:
    from visual_intelligence import find_visual_target as vi_find_visual_target

    params = dict(step.get("parameters") or {})
    anchor = step.get("visual_anchor") or {}
    if not anchor:
        return params, {"status": "no_anchor", "should_abort": False}

    target = vi_find_visual_target(
        anchor=anchor,
        ocr_result={"status": "success", "texts": observed_state.get("texts", [])},
        ui_elements={"status": "success", "elements": observed_state.get("elements", [])},
        min_confidence=min_confidence,
    )
    if target.get("status") != "success":
        return params, target

    resolved = target.get("target") or {}
    if step.get("action_type") in {"move_mouse", "click"}:
        params["x"] = resolved.get("x")
        params["y"] = resolved.get("y")
        if resolved.get("text"):
            params["target_text"] = resolved.get("text")
    if step.get("action_type") == "click_element" and resolved.get("text"):
        params["text"] = resolved.get("text")
    return params, target


def _apply_adaptive_fallback(step: Dict[str, object], executors: Dict[str, object], verifier) -> bool:
    action_type = step.get("action_type")
    params = dict(step.get("parameters") or {})

    if action_type == "click" and params.get("target_text") and "click_element" in executors:
        outcome = executors["click_element"](text=params.get("target_text"))
        if outcome.get("status") == "success":
            observed = verifier()
            if _verify_step(step, observed):
                return True

    if action_type == "move_mouse" and {"x", "y"}.issubset(params.keys()) and "move_mouse" in executors:
        for delta in [(-8, -8), (8, 8), (0, 12)]:
            outcome = executors["move_mouse"](int(params["x"]) + delta[0], int(params["y"]) + delta[1])
            if outcome.get("status") == "success":
                observed = verifier()
                if _verify_step(step, observed):
                    return True

    for hint in step.get("fallback_hints") or []:
        hint_action = hint.get("action_type")
        if hint_action in executors:
            outcome = executors[hint_action](**(hint.get("parameters") or {}))
            if outcome.get("status") == "success":
                observed = verifier()
                if _verify_step(step, observed):
                    return True

    return False


def replay_workflow(
    instance_path: str,
    user_id: int,
    workflow_id: str,
    *,
    executors: Dict[str, object],
    verifier,
    step_guard=None,
    max_steps: int = 25,
) -> Dict[str, object]:
    data = _load_data(instance_path, user_id)
    workflow = get_workflow(instance_path, user_id, workflow_id)
    if not workflow:
        return {"status": "error", "message": "Workflow not found"}

    steps = workflow.get("steps", [])[: int(max_steps)]
    results: List[Dict[str, object]] = []

    for step in steps:
        action_type = step.get("action_type")
        action = executors.get(action_type)
        if action is None:
            results.append({"step_id": step.get("step_id"), "status": "error", "message": f"Unsupported action: {action_type}"})
            break
        if callable(step_guard):
            guard = step_guard(action_type, step.get("parameters") or {})
            if guard and guard.get("allowed") is False:
                results.append({
                    "step_id": step.get("step_id"),
                    "status": "error",
                    "message": guard.get("message") or "Workflow safety policy blocked step execution.",
                    "error_type": guard.get("error_type") or "os_tool_safety_block",
                })
                break

        pre_observation = verifier()
        if not _verify_step({"verification_rule": step.get("context", {}).get("precondition") or {}}, pre_observation):
            results.append({"step_id": step.get("step_id"), "status": "error", "message": "Precondition check failed"})
            break

        resolved_params, target_info = _resolve_parameters_with_anchor(step, pre_observation)
        if target_info.get("should_abort"):
            results.append({"step_id": step.get("step_id"), "status": "error", "message": "Low-confidence visual target", "target_info": target_info})
            break

        outcome = action(**resolved_params)
        post_observation = verifier()
        verified = _verify_step(step, post_observation)

        if outcome.get("status") != "success" or not verified:
            recovered = _apply_adaptive_fallback(step, executors, verifier)
            if not recovered:
                results.append({
                    "step_id": step.get("step_id"),
                    "status": "error",
                    "message": "Verification failed",
                    "action_outcome": outcome,
                })
                break
            results.append({"step_id": step.get("step_id"), "status": "recovered"})
            continue

        results.append({"step_id": step.get("step_id"), "status": "success"})

    success = bool(results) and all(r.get("status") in {"success", "recovered"} for r in results)

    # update workflow metrics
    for item in data.get("workflows", []):
        if item.get("workflow_id") != workflow_id:
            continue
        item["run_count"] = int(item.get("run_count") or 0) + 1
        if success:
            item["success_count"] = int(item.get("success_count") or 0) + 1
        item["success_rate"] = round(item["success_count"] / max(item["run_count"], 1), 3)
        item["last_used"] = time.time()
        break
    _save_data(instance_path, user_id, data)

    upsert_fact(
        int(user_id),
        scope="user",
        key=f"workflow_run::{workflow_id}",
        value=f"Workflow run {'succeeded' if success else 'failed'} with {len(results)} step results",
        source_conversation_id=None,
        source_message_index=None,
        confidence=0.8,
    )

    return {
        "status": "success" if success else "error",
        "workflow_id": workflow_id,
        "results": results,
        "fallback_to_agent": not success,
    }
