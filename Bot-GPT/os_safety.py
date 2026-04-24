import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

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


OBSERVE_TOOLS = {
    "capture_screen",
    "ocr_screen",
    "detect_ui_elements",
    "extract_visible_text",
    "verify_visual_state",
    "visual_feedback_step",
}

CAUTION_TOOLS = {
    "open_url",
    "find_element_by_text",
    "click_element",
    "move_mouse",
    "click",
    "type_text",
    "press_key",
    "open_app",
    "focus_window",
    "run_workflow",
}

DANGEROUS_TOOLS = {
    "close_window",
}


def get_tool_safety_category(tool_name: str) -> str:
    if tool_name in DANGEROUS_TOOLS:
        return "dangerous"
    if tool_name in CAUTION_TOOLS:
        return "caution"
    if tool_name in OBSERVE_TOOLS:
        return "observe"
    return "normal"


def _normalize_allowed_users(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        if not cleaned:
            return []
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            return [part.strip() for part in cleaned.split(",") if part.strip()]
    if isinstance(raw_value, (list, tuple, set)):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return []


def _is_user_allowed(config: Dict[str, Any], user: Any) -> bool:
    allowed_users = _normalize_allowed_users(config.get("OS_AGENT_ALLOWED_USERS"))
    if not allowed_users:
        return True
    user_id = str(getattr(user, "id", "")).strip()
    username = str(getattr(user, "username", "")).strip()
    return user_id in allowed_users or (username and username in allowed_users)


def _safety_error(reason: str) -> Dict[str, Any]:
    return {
        "tool_name": None,
        "status": "error",
        "result": None,
        "error_type": "os_tool_safety_block",
        "error_message": reason,
        "retryable": False,
        "reason": reason,
    }


def evaluate_tool_policy(tool_name: str, user: Any, config: Dict[str, Any], execution_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    execution_context = execution_context or {}
    category = get_tool_safety_category(tool_name)
    mode = str(execution_context.get("mode") or "standard").lower()
    os_control_enabled = bool(execution_context.get("os_control_enabled", False))
    explicit_user_intent = bool(execution_context.get("explicit_user_intent", False))

    policy = {
        "allowed": True,
        "category": category,
        "mode": mode,
        "requires_approval": False,
        "reason": None,
    }

    if category == "normal":
        return policy

    if not bool(config.get("OS_AGENT_ENABLED", False)):
        policy["allowed"] = False
        policy["reason"] = "OS-agent is disabled. Enable OS_AGENT_ENABLED to use OS/browser/workflow tools."
        return policy

    if not _is_user_allowed(config, user):
        policy["allowed"] = False
        policy["reason"] = "User is not allowed to use OS/browser/workflow tools."
        return policy

    if mode == "standard" and category in {"caution", "dangerous"}:
        policy["allowed"] = False
        policy["reason"] = "Standard mode only permits observation tools for OS/browser safety."
        return policy

    if mode == "deep" and category in {"caution", "dangerous"}:
        if not explicit_user_intent:
            policy["allowed"] = False
            policy["reason"] = "Deep mode requires explicit user intent for OS/browser action tools."
            return policy
        if not os_control_enabled:
            policy["allowed"] = False
            policy["reason"] = "OS control session is disabled; explicit enablement is required."
            return policy

    if mode == "agent" and category in {"caution", "dangerous"} and not os_control_enabled:
        policy["allowed"] = False
        policy["reason"] = "Agent mode OS/browser actions require os_control_enabled=true."
        return policy

    if category == "dangerous" and mode != "agent":
        policy["allowed"] = False
        policy["reason"] = "Dangerous OS actions are restricted to agent mode with approval."
        return policy

    if bool(config.get("OS_AGENT_SAFE_MODE", True)):
        if category == "caution" and bool(config.get("OS_AGENT_REQUIRE_APPROVAL_FOR_CAUTION", True)):
            policy["requires_approval"] = True
        if category == "dangerous" and bool(config.get("OS_AGENT_REQUIRE_APPROVAL_FOR_DANGEROUS", True)):
            policy["requires_approval"] = True

    return policy


APPROVALS_FILE = "os_tool_approvals.json"


def _approvals_path(instance_path: str) -> str:
    return os.path.join(instance_path, APPROVALS_FILE)


def _read_approvals(instance_path: str) -> Dict[str, Any]:
    path = _approvals_path(instance_path)
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return {"requests": []}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
                if isinstance(payload, dict) and isinstance(payload.get("requests"), list):
                    return payload
        except Exception:
            pass
    return {"requests": []}


def _write_approvals(instance_path: str, payload: Dict[str, Any]) -> None:
    path = _approvals_path(instance_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = FileLock(f"{path}.lock")
    with lock:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


def _approval_match(req: Dict[str, Any], *, user_id: int, tool_name: str, params: Dict[str, Any]) -> bool:
    return (
        int(req.get("user_id") or -1) == int(user_id)
        and req.get("tool_name") == tool_name
        and (req.get("params") or {}) == (params or {})
        and req.get("status") in {"pending", "approved"}
    )


def get_or_create_approval_request(instance_path: str, *, user_id: int, tool_name: str, params: Dict[str, Any], risk_level: str, reason: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = _read_approvals(instance_path)
    for req in payload.get("requests", []):
        if _approval_match(req, user_id=user_id, tool_name=tool_name, params=params):
            return req

    request_obj = {
        "request_id": uuid.uuid4().hex,
        "user_id": int(user_id),
        "tool_name": tool_name,
        "params": params or {},
        "risk_level": risk_level,
        "reason": reason,
        "status": "pending",
        "context": context or {},
        "created_at": time.time(),
        "resolved_at": None,
        "resolved_by": None,
    }
    payload.setdefault("requests", []).append(request_obj)
    _write_approvals(instance_path, payload)
    return request_obj


def resolve_approval_request(instance_path: str, request_id: str, *, status: str, resolved_by: Optional[int] = None) -> Optional[Dict[str, Any]]:
    payload = _read_approvals(instance_path)
    if status not in {"approved", "rejected"}:
        return None
    for req in payload.get("requests", []):
        if req.get("request_id") != request_id:
            continue
        req["status"] = status
        req["resolved_at"] = time.time()
        req["resolved_by"] = resolved_by
        _write_approvals(instance_path, payload)
        return req
    return None


def list_pending_approvals(instance_path: str, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    payload = _read_approvals(instance_path)
    pending = [req for req in payload.get("requests", []) if req.get("status") == "pending"]
    if user_id is None:
        return pending
    return [req for req in pending if int(req.get("user_id") or -1) == int(user_id)]


def consume_approved_request(instance_path: str, *, user_id: int, tool_name: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = _read_approvals(instance_path)
    for req in payload.get("requests", []):
        if (
            int(req.get("user_id") or -1) == int(user_id)
            and req.get("tool_name") == tool_name
            and (req.get("params") or {}) == (params or {})
            and req.get("status") == "approved"
        ):
            req["status"] = "consumed"
            req["resolved_at"] = time.time()
            _write_approvals(instance_path, payload)
            return req
    return None


def build_pending_approval_result(*, tool_name: str, reason: str, approval_request: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tool_name": tool_name,
        "status": "pending_approval",
        "result": {
            "status": "pending_approval",
            "approval_request": approval_request,
            "reason": reason,
        },
        "error_type": "pending_approval",
        "error_message": reason,
        "retryable": False,
    }
