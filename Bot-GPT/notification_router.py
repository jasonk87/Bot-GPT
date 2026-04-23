import json
import os
import time
import uuid
from typing import Dict

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


def _activity_path(instance_path: str, user_id: int) -> str:
    return os.path.join(instance_path, str(user_id), "activity_state.json")


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


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = FileLock(f"{path}.lock")
    with lock:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


def mark_user_activity(instance_path: str, user_id: int, channel: str = "ui") -> Dict[str, object]:
    state = {
        "user_id": int(user_id),
        "last_active_at": time.time(),
        "channel": channel,
    }
    _write_json(_activity_path(instance_path, user_id), state)
    return state


def get_user_activity(instance_path: str, user_id: int) -> Dict[str, object]:
    state = _read_json(_activity_path(instance_path, user_id), {})
    if not isinstance(state, dict):
        return {}
    return state


def decide_route(instance_path: str, user_id: int, idle_threshold_seconds: int = 90) -> str:
    activity = get_user_activity(instance_path, user_id)
    last_active = float(activity.get("last_active_at") or 0)
    if last_active and (time.time() - last_active) <= idle_threshold_seconds:
        return "active_ui"
    return "stored"


def build_notification(*, user_id: int, task_id: str, title: str, message: str, severity: str = "info") -> Dict[str, object]:
    return {
        "notification_id": uuid.uuid4().hex,
        "user_id": int(user_id),
        "task_id": task_id,
        "title": title,
        "message": message,
        "severity": severity,
        "created_at": time.time(),
        "read": False,
    }


def route_notification(instance_path: str, socketio, notification: Dict[str, object], idle_threshold_seconds: int = 90) -> str:
    route = decide_route(instance_path, int(notification["user_id"]), idle_threshold_seconds=idle_threshold_seconds)
    if route == "active_ui" and socketio is not None:
        socketio.emit("proactive_notification", notification, room=f"user_{notification['user_id']}")
    return route
