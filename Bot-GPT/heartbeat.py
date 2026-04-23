import json
import os
import time
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


def _heartbeat_path(instance_path: str) -> str:
    return os.path.join(instance_path, "heartbeat.json")


def load_heartbeat(instance_path: str) -> Dict[str, object]:
    path = _heartbeat_path(instance_path)
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return {
                "last_heartbeat": None,
                "last_task_activity": None,
                "active_workers": 0,
                "queue_depth": 0,
                "is_running": False,
                "last_error": None,
            }
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return {
        "last_heartbeat": None,
        "last_task_activity": None,
        "active_workers": 0,
        "queue_depth": 0,
        "is_running": False,
        "last_error": "invalid_heartbeat_payload",
    }


def write_heartbeat(instance_path: str, **updates) -> Dict[str, object]:
    path = _heartbeat_path(instance_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state = load_heartbeat(instance_path)
    state.update(updates)
    state["last_heartbeat"] = time.time()

    lock = FileLock(f"{path}.lock")
    with lock:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
    return state
