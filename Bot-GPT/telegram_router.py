import hashlib
import json
import os
import secrets
import time
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

from heartbeat import load_heartbeat
from memory_store import upsert_fact
from repo_index import load_repo_index
from task_scheduler import list_notifications, list_tasks

PAIRING_FILE = "telegram_pairing.json"


def _pairing_path(instance_path: str) -> str:
    return os.path.join(instance_path, PAIRING_FILE)


def _read_pairing_data(instance_path: str) -> Dict[str, object]:
    path = _pairing_path(instance_path)
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return {"mappings": {}, "challenges": []}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    data.setdefault("mappings", {})
                    data.setdefault("challenges", [])
                    return data
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return {"mappings": {}, "challenges": []}


def _write_pairing_data(instance_path: str, payload: Dict[str, object]) -> None:
    path = _pairing_path(instance_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = FileLock(f"{path}.lock")
    with lock:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


def _hash_pairing_code(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _cleanup_expired_challenges(data: Dict[str, object]) -> None:
    now = time.time()
    data["challenges"] = [
        challenge
        for challenge in data.get("challenges", [])
        if float(challenge.get("expires_at") or 0) > now and not challenge.get("used")
    ]


def create_pairing_code(instance_path: str, user_id: int, expiry_seconds: int = 300) -> Dict[str, object]:
    data = _read_pairing_data(instance_path)
    _cleanup_expired_challenges(data)

    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    expires_at = time.time() + max(60, int(expiry_seconds))

    # invalidate older pending codes for this user
    for challenge in data["challenges"]:
        if int(challenge.get("user_id") or -1) == int(user_id) and not challenge.get("used"):
            challenge["used"] = True

    challenge = {
        "user_id": int(user_id),
        "code_hash": _hash_pairing_code(code, salt),
        "salt": salt,
        "created_at": time.time(),
        "expires_at": expires_at,
        "used": False,
    }
    data["challenges"].append(challenge)
    _write_pairing_data(instance_path, data)

    return {
        "pairing_code": code,
        "expires_at": expires_at,
    }


def get_pairing_status_for_user(instance_path: str, user_id: int) -> Dict[str, object]:
    data = _read_pairing_data(instance_path)
    mappings = data.get("mappings", {})
    linked_accounts = [
        {
            "telegram_user_id": tg_user_id,
            "telegram_username": payload.get("telegram_username"),
            "paired_at": payload.get("paired_at"),
            "last_command_at": payload.get("last_command_at"),
        }
        for tg_user_id, payload in mappings.items()
        if int(payload.get("user_id") or -1) == int(user_id)
    ]
    return {"linked_accounts": linked_accounts}


def get_local_user_for_telegram(instance_path: str, telegram_user_id: int) -> Optional[int]:
    data = _read_pairing_data(instance_path)
    mapping = data.get("mappings", {}).get(str(telegram_user_id))
    if not mapping:
        return None
    return int(mapping.get("user_id"))


def get_telegram_targets_for_user(instance_path: str, user_id: int) -> List[Dict[str, object]]:
    data = _read_pairing_data(instance_path)
    targets = []
    for tg_user_id, payload in data.get("mappings", {}).items():
        if int(payload.get("user_id") or -1) == int(user_id):
            targets.append({
                "telegram_user_id": int(tg_user_id),
                "telegram_username": payload.get("telegram_username"),
            })
    return targets


def unpair_telegram_user(instance_path: str, user_id: int, telegram_user_id: Optional[int] = None) -> int:
    data = _read_pairing_data(instance_path)
    mappings = data.get("mappings", {})
    removed = 0

    for key in list(mappings.keys()):
        payload = mappings.get(key) or {}
        if int(payload.get("user_id") or -1) != int(user_id):
            continue
        if telegram_user_id is not None and int(key) != int(telegram_user_id):
            continue
        mappings.pop(key, None)
        removed += 1

    _write_pairing_data(instance_path, data)
    return removed


def complete_pairing(
    instance_path: str,
    telegram_user_id: int,
    telegram_username: Optional[str],
    code: str,
) -> Tuple[bool, str, Optional[int]]:
    data = _read_pairing_data(instance_path)
    now = time.time()

    for challenge in data.get("challenges", []):
        if challenge.get("used"):
            continue
        if float(challenge.get("expires_at") or 0) < now:
            continue

        expected = challenge.get("code_hash")
        salt = str(challenge.get("salt") or "")
        if expected != _hash_pairing_code(code.strip(), salt):
            continue

        user_id = int(challenge.get("user_id"))
        challenge["used"] = True

        # enforce one telegram account -> one user mapping
        data.setdefault("mappings", {})
        data["mappings"][str(telegram_user_id)] = {
            "user_id": user_id,
            "telegram_username": telegram_username,
            "paired_at": now,
            "last_command_at": now,
        }
        _cleanup_expired_challenges(data)
        _write_pairing_data(instance_path, data)
        return True, "Pairing successful. You can now use /status, /tasks, /notify, /run, /repo.", user_id

    _cleanup_expired_challenges(data)
    _write_pairing_data(instance_path, data)
    return False, "Invalid or expired pairing code. Generate a new code from the web app and try again.", None


def record_telegram_command(instance_path: str, telegram_user_id: int) -> None:
    data = _read_pairing_data(instance_path)
    mapping = data.get("mappings", {}).get(str(telegram_user_id))
    if not mapping:
        return
    mapping["last_command_at"] = time.time()
    _write_pairing_data(instance_path, data)


def _format_status(instance_path: str, user_id: int) -> str:
    heartbeat = load_heartbeat(instance_path)
    tasks = list_tasks(instance_path, user_id)
    active = [task for task in tasks if task.get("status") == "active"]
    unread_notifications = list_notifications(instance_path, user_id, unread_only=True)
    return (
        "System status\n"
        f"- runner: {'online' if heartbeat.get('is_running') else 'offline'}\n"
        f"- last heartbeat: {int(heartbeat.get('last_heartbeat') or 0)}\n"
        f"- active tasks: {len(active)}\n"
        f"- unread notifications: {len(unread_notifications)}"
    )


def _format_tasks(instance_path: str, user_id: int) -> str:
    tasks = list_tasks(instance_path, user_id)
    if not tasks:
        return "No tasks configured."
    lines = ["Tasks:"]
    for task in tasks[:8]:
        lines.append(
            f"- {task.get('name')} ({task.get('task_id')[:8]}) [{task.get('status')}] next={int(task.get('next_run') or 0)}"
        )
    return "\n".join(lines)


def _format_notifications(instance_path: str, user_id: int) -> str:
    notifications = list_notifications(instance_path, user_id)
    if not notifications:
        return "No notifications yet."
    lines = ["Recent notifications:"]
    for note in notifications[-5:]:
        lines.append(f"- {note.get('title')}: {note.get('message')}")
    return "\n".join(lines)


def _format_repo(instance_path: str, user_id: int) -> str:
    payload = load_repo_index(user_id)
    selected = payload.get("selected_repo")
    if not selected:
        return "No repository selected."
    return (
        "Selected repository\n"
        f"- name: {selected.get('name')}\n"
        f"- path: {selected.get('path')}\n"
        f"- language: {selected.get('language')}"
    )


def _run_remote_instruction(app, user_id: int, instruction: str) -> str:
    from task_runner import execute_task_instruction

    result = execute_task_instruction(app, user_id, instruction)
    return result.get("message", "Instruction completed.")


def handle_telegram_command(app, telegram_user_id: int, telegram_username: Optional[str], text: str) -> str:
    instance_path = app.instance_path
    command_text = (text or "").strip()
    if not command_text:
        return "Empty command. Use /status, /tasks, /notify, /run <instruction>, /repo, or /pair <code>."

    if command_text.startswith("/pair"):
        parts = command_text.split(maxsplit=1)
        if len(parts) == 1:
            return "To pair, generate a code in the web app and send /pair <code>."
        ok, message, user_id = complete_pairing(instance_path, telegram_user_id, telegram_username, parts[1])
        if ok and user_id is not None:
            upsert_fact(
                user_id,
                scope="user",
                key=f"telegram_pairing::{telegram_user_id}",
                value="Telegram account paired successfully",
                source_conversation_id=None,
                source_message_index=None,
                confidence=0.9,
            )
        return message

    local_user_id = get_local_user_for_telegram(instance_path, telegram_user_id)
    if not local_user_id:
        return "This Telegram account is not paired. Run /pair <code> after generating a code in the web app."

    record_telegram_command(instance_path, telegram_user_id)

    try:
        if command_text == "/status":
            message = _format_status(instance_path, local_user_id)
        elif command_text == "/tasks":
            message = _format_tasks(instance_path, local_user_id)
        elif command_text == "/notify":
            message = _format_notifications(instance_path, local_user_id)
        elif command_text == "/repo":
            message = _format_repo(instance_path, local_user_id)
        elif command_text.startswith("/run"):
            instruction = command_text[len("/run"):].strip()
            if not instruction:
                return "Usage: /run <task_id or safe instruction>."
            message = _run_remote_instruction(app, local_user_id, instruction)
        else:
            return "Unknown command. Supported: /status, /tasks, /notify, /run, /repo, /pair."

        upsert_fact(
            local_user_id,
            scope="user",
            key=f"telegram_command::{int(time.time())}",
            value=f"Executed command: {command_text[:80]}",
            source_conversation_id=None,
            source_message_index=None,
            confidence=0.75,
        )
        return message
    except Exception:
        return "Command failed. Please retry or check system status from the web app."
