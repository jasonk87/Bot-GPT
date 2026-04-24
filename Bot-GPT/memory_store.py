import json
import os
import time
from typing import Dict, List, Optional

from flask import current_app


def _memory_path(user_id: int) -> str:
    return os.path.join(current_app.instance_path, str(user_id), "hybrid_memory.json")


def load_memory(user_id: int) -> Dict[str, object]:
    path = _memory_path(user_id)
    if not os.path.exists(path):
        return {"user_facts": [], "project_facts": {}, "sessions": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                data.setdefault("user_facts", [])
                data.setdefault("project_facts", {})
                data.setdefault("sessions", {})
                return data
    except Exception:
        pass
    return {"user_facts": [], "project_facts": {}, "sessions": {}}


def save_memory(user_id: int, payload: Dict[str, object]) -> None:
    path = _memory_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def upsert_fact(
    user_id: int,
    *,
    scope: str,
    key: str,
    value: str,
    source_conversation_id: Optional[str],
    source_message_index: Optional[int],
    confidence: float = 0.7,
    project_key: Optional[str] = None,
) -> Dict[str, object]:
    memory = load_memory(user_id)
    target: List[Dict[str, object]]
    if scope == "project" and project_key:
        memory["project_facts"].setdefault(project_key, [])
        target = memory["project_facts"][project_key]
    else:
        target = memory["user_facts"]

    existing = next((f for f in target if f.get("key") == key), None)
    entry = {
        "key": key,
        "value": value,
        "source": {
            "conversation_id": source_conversation_id,
            "message_index": source_message_index,
        },
        "timestamp": time.time(),
        "confidence": float(confidence),
        "scope": scope,
        "project_key": project_key,
    }
    if existing:
        existing.update(entry)
        stored = existing
    else:
        target.append(entry)
        stored = entry
    save_memory(user_id, memory)
    return stored


def list_facts(user_id: int, scope: str = "user", project_key: Optional[str] = None) -> List[Dict[str, object]]:
    memory = load_memory(user_id)
    if scope == "project" and project_key:
        return list(memory.get("project_facts", {}).get(project_key, []))
    return list(memory.get("user_facts", []))


def update_session_memory(user_id: int, conversation_id: str, summary: str, key_notes: List[str]) -> None:
    memory = load_memory(user_id)
    memory["sessions"][conversation_id] = {
        "summary": summary,
        "key_notes": key_notes[:12],
        "updated_at": time.time(),
    }
    save_memory(user_id, memory)


def get_session_memory(user_id: int, conversation_id: str) -> Dict[str, object]:
    memory = load_memory(user_id)
    return memory.get("sessions", {}).get(conversation_id, {})
