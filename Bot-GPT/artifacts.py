import os
import time
from typing import Any, Dict, List, Optional

from models import load_conversation, save_conversation
from shared_paths import get_conversation_path


def infer_artifact_type(path: str) -> str:
    lower = str(path or "").lower()
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "markdown"
    if lower.endswith(".html") or lower.endswith(".htm"):
        return "html"
    if any(lower.endswith(ext) for ext in [
        ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".json",
        ".sql", ".sh", ".txt", ".yml", ".yaml", ".xml"
    ]):
        return "code"
    return "unknown"


def _normalize_artifacts(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        artifact_id = item.get("artifact_id") or item.get("path")
        if not artifact_id:
            continue
        normalized.append({
            "artifact_id": artifact_id,
            "conversation_id": item.get("conversation_id"),
            "artifact_type": item.get("artifact_type") or infer_artifact_type(artifact_id),
            "last_updated_at": float(item.get("last_updated_at") or time.time()),
            "title": item.get("title") or os.path.basename(artifact_id),
        })
    normalized.sort(key=lambda x: x.get("last_updated_at", 0), reverse=True)
    return normalized


def list_artifacts_for_conversation(owner_id: Any, conversation_id: str) -> List[Dict[str, Any]]:
    convo_path = get_conversation_path(owner_id, conversation_id)
    conversation = load_conversation(convo_path) or {}
    return _normalize_artifacts(conversation.get("artifacts"))


def upsert_artifact_metadata(
    owner_id: Any,
    conversation_id: str,
    artifact_id: str,
    *,
    artifact_type: Optional[str] = None,
    title: Optional[str] = None,
    updated_at: Optional[float] = None,
) -> Dict[str, Any]:
    convo_path = get_conversation_path(owner_id, conversation_id)
    conversation = load_conversation(convo_path) or {}
    artifacts = _normalize_artifacts(conversation.get("artifacts"))
    timestamp = float(updated_at or time.time())

    existing = next((a for a in artifacts if a.get("artifact_id") == artifact_id), None)
    if existing:
        existing["artifact_type"] = artifact_type or existing.get("artifact_type") or infer_artifact_type(artifact_id)
        existing["last_updated_at"] = timestamp
        existing["title"] = title or existing.get("title") or os.path.basename(artifact_id)
    else:
        artifacts.append({
            "artifact_id": artifact_id,
            "conversation_id": conversation_id,
            "artifact_type": artifact_type or infer_artifact_type(artifact_id),
            "last_updated_at": timestamp,
            "title": title or os.path.basename(artifact_id),
        })

    artifacts.sort(key=lambda x: x.get("last_updated_at", 0), reverse=True)
    conversation["artifacts"] = artifacts
    conversation["last_active_artifact_id"] = artifact_id
    save_conversation(convo_path, conversation)
    return next(a for a in artifacts if a.get("artifact_id") == artifact_id)


def set_last_active_artifact(owner_id: Any, conversation_id: str, artifact_id: Optional[str]) -> None:
    convo_path = get_conversation_path(owner_id, conversation_id)
    conversation = load_conversation(convo_path) or {}
    conversation["last_active_artifact_id"] = artifact_id
    save_conversation(convo_path, conversation)


def rename_artifact_metadata(owner_id: Any, conversation_id: str, old_path: str, new_path: str) -> None:
    convo_path = get_conversation_path(owner_id, conversation_id)
    conversation = load_conversation(convo_path) or {}
    artifacts = _normalize_artifacts(conversation.get("artifacts"))
    changed = False
    for artifact in artifacts:
        if artifact.get("artifact_id") == old_path:
            artifact["artifact_id"] = new_path
            artifact["title"] = os.path.basename(new_path)
            artifact["artifact_type"] = infer_artifact_type(new_path)
            artifact["last_updated_at"] = time.time()
            changed = True
            break
    if conversation.get("last_active_artifact_id") == old_path:
        conversation["last_active_artifact_id"] = new_path
        changed = True
    if changed:
        artifacts.sort(key=lambda x: x.get("last_updated_at", 0), reverse=True)
        conversation["artifacts"] = artifacts
        save_conversation(convo_path, conversation)


def remove_artifact_metadata(owner_id: Any, conversation_id: str, artifact_id: str) -> None:
    convo_path = get_conversation_path(owner_id, conversation_id)
    conversation = load_conversation(convo_path) or {}
    artifacts = _normalize_artifacts(conversation.get("artifacts"))
    filtered = [a for a in artifacts if a.get("artifact_id") != artifact_id]
    if len(filtered) == len(artifacts):
        return
    conversation["artifacts"] = filtered
    if conversation.get("last_active_artifact_id") == artifact_id:
        conversation["last_active_artifact_id"] = filtered[0]["artifact_id"] if filtered else None
    save_conversation(convo_path, conversation)
