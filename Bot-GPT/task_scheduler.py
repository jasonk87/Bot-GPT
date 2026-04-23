import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
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


ALLOWED_TASK_TYPES = {"reminder", "monitor", "repo_check", "custom", "periodic_check"}
ALLOWED_STATUS = {"active", "paused", "failed"}


@dataclass
class BackgroundTask:
    task_id: str
    user_id: int
    name: str
    description: str
    task_type: str
    schedule: Dict[str, object]
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    last_result: Optional[Dict[str, object]] = None
    conditions: Optional[Dict[str, object]] = None
    delivery_preferences: Optional[Dict[str, object]] = None
    payload: Optional[Dict[str, object]] = None

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _tasks_path(instance_path: str, user_id: int) -> str:
    return os.path.join(instance_path, str(user_id), "background_tasks.json")


def _notifications_path(instance_path: str, user_id: int) -> str:
    return os.path.join(instance_path, str(user_id), "notifications.json")


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


def parse_schedule(schedule: Dict[str, object]) -> Tuple[str, int]:
    schedule_type = str(schedule.get("type", "interval")).strip().lower()
    if schedule_type == "interval":
        every_seconds = int(schedule.get("every_seconds") or 0)
        if every_seconds <= 0:
            every_minutes = int(schedule.get("every_minutes") or 0)
            every_hours = int(schedule.get("every_hours") or 0)
            every_seconds = every_minutes * 60 + every_hours * 3600
        if every_seconds <= 0:
            raise ValueError("Interval schedule requires every_seconds/every_minutes/every_hours > 0")
        return "interval", every_seconds

    if schedule_type == "cron":
        expression = str(schedule.get("expression") or "").strip()
        if not expression:
            raise ValueError("Cron schedule requires expression")
        # v1 cron support: */N * * * *
        parts = expression.split()
        if len(parts) != 5 or not parts[0].startswith("*/"):
            raise ValueError("Cron expression supports only '*/N * * * *' in v1")
        minutes = int(parts[0][2:])
        if minutes <= 0:
            raise ValueError("Cron interval minutes must be > 0")
        return "cron", minutes * 60

    raise ValueError(f"Unsupported schedule type: {schedule_type}")


def compute_next_run(schedule: Dict[str, object], from_timestamp: Optional[float] = None) -> float:
    from_timestamp = from_timestamp if from_timestamp is not None else time.time()
    _, interval_seconds = parse_schedule(schedule)
    return float(from_timestamp + interval_seconds)


def create_task(instance_path: str, user_id: int, payload: Dict[str, object]) -> Dict[str, object]:
    now = time.time()
    schedule = payload.get("schedule") or {}
    task_type = str(payload.get("task_type") or "").strip().lower()
    if task_type not in ALLOWED_TASK_TYPES:
        raise ValueError(f"Unsupported task_type: {task_type}")

    parse_schedule(schedule)
    task = BackgroundTask(
        task_id=str(payload.get("task_id") or uuid.uuid4().hex),
        user_id=int(user_id),
        name=str(payload.get("name") or "Background task").strip(),
        description=str(payload.get("description") or "").strip(),
        task_type=task_type,
        schedule=schedule,
        status="active",
        created_at=now,
        updated_at=now,
        next_run=compute_next_run(schedule, now),
        conditions=payload.get("conditions") or {},
        delivery_preferences=payload.get("delivery_preferences") or {},
        payload=payload.get("payload") or {},
    )

    tasks = list_tasks(instance_path, user_id)
    tasks.append(task.to_dict())
    _write_json(_tasks_path(instance_path, user_id), tasks)
    return task.to_dict()


def list_tasks(instance_path: str, user_id: int) -> List[Dict[str, object]]:
    tasks = _read_json(_tasks_path(instance_path, user_id), [])
    if not isinstance(tasks, list):
        return []
    return tasks


def list_all_tasks(instance_path: str) -> List[Dict[str, object]]:
    all_tasks: List[Dict[str, object]] = []
    if not os.path.isdir(instance_path):
        return all_tasks

    for entry in os.listdir(instance_path):
        if not entry.isdigit():
            continue
        all_tasks.extend(list_tasks(instance_path, int(entry)))
    return all_tasks


def get_task(instance_path: str, user_id: int, task_id: str) -> Optional[Dict[str, object]]:
    for task in list_tasks(instance_path, user_id):
        if task.get("task_id") == task_id:
            return task
    return None


def save_task(instance_path: str, user_id: int, task: Dict[str, object]) -> Dict[str, object]:
    tasks = list_tasks(instance_path, user_id)
    updated = []
    found = False
    for item in tasks:
        if item.get("task_id") == task.get("task_id"):
            found = True
            updated.append(task)
        else:
            updated.append(item)
    if not found:
        updated.append(task)
    _write_json(_tasks_path(instance_path, user_id), updated)
    return task


def update_task_status(instance_path: str, user_id: int, task_id: str, status: str) -> Dict[str, object]:
    if status not in ALLOWED_STATUS:
        raise ValueError(f"Unsupported status: {status}")
    task = get_task(instance_path, user_id, task_id)
    if not task:
        raise KeyError(task_id)
    task["status"] = status
    task["updated_at"] = time.time()
    if status == "active" and not task.get("next_run"):
        task["next_run"] = compute_next_run(task.get("schedule") or {}, time.time())
    save_task(instance_path, user_id, task)
    return task


def delete_task(instance_path: str, user_id: int, task_id: str) -> bool:
    tasks = list_tasks(instance_path, user_id)
    filtered = [task for task in tasks if task.get("task_id") != task_id]
    if len(filtered) == len(tasks):
        return False
    _write_json(_tasks_path(instance_path, user_id), filtered)
    return True


def mark_task_result(instance_path: str, user_id: int, task_id: str, result: Dict[str, object]) -> Dict[str, object]:
    task = get_task(instance_path, user_id, task_id)
    if not task:
        raise KeyError(task_id)

    now = time.time()
    task["last_run"] = now
    task["updated_at"] = now
    task["last_result"] = result
    if task.get("status") == "active":
        task["next_run"] = compute_next_run(task.get("schedule") or {}, now)

    save_task(instance_path, user_id, task)
    return task


def enqueue_notification(instance_path: str, user_id: int, notification: Dict[str, object]) -> Dict[str, object]:
    payload = _read_json(_notifications_path(instance_path, user_id), [])
    if not isinstance(payload, list):
        payload = []
    payload.append(notification)
    _write_json(_notifications_path(instance_path, user_id), payload[-200:])
    return notification


def list_notifications(instance_path: str, user_id: int, unread_only: bool = False) -> List[Dict[str, object]]:
    notifications = _read_json(_notifications_path(instance_path, user_id), [])
    if not isinstance(notifications, list):
        return []
    if unread_only:
        return [n for n in notifications if not n.get("read")]
    return notifications


def mark_notifications_read(instance_path: str, user_id: int) -> int:
    notifications = list_notifications(instance_path, user_id)
    now = time.time()
    updated = 0
    for notification in notifications:
        if not notification.get("read"):
            notification["read"] = True
            notification["read_at"] = now
            updated += 1
    _write_json(_notifications_path(instance_path, user_id), notifications)
    return updated


def format_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
