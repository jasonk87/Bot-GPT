import math
import re
from typing import Dict, List, Optional

from memory_store import list_facts, get_session_memory
from memory import MemoryManager


def _tokenize(text: str) -> set:
    return {token for token in re.split(r"[^a-zA-Z0-9]+", (text or "").lower()) if token}


def _score_fact(query: str, fact: Dict[str, object]) -> float:
    q_tokens = _tokenize(query)
    f_tokens = _tokenize(f"{fact.get('key', '')} {fact.get('value', '')}")
    if not q_tokens:
        overlap = 0.0
    else:
        overlap = len(q_tokens & f_tokens) / max(1, len(q_tokens))
    recency = float(fact.get("timestamp") or 0.0)
    return overlap * 0.7 + math.log1p(max(recency, 1)) * 0.000001 + float(fact.get("confidence") or 0) * 0.3


def retrieve_relevant_memory(
    user_id: int,
    query: str,
    *,
    project_key: Optional[str] = None,
    top_k: int = 6,
) -> Dict[str, List[Dict[str, object]]]:
    project_facts = list_facts(user_id, scope="project", project_key=project_key) if project_key else []
    user_facts = list_facts(user_id, scope="user")

    ranked_project = sorted(project_facts, key=lambda f: _score_fact(query, f), reverse=True)[: max(0, top_k // 2)]
    ranked_user = sorted(user_facts, key=lambda f: _score_fact(query, f), reverse=True)[: top_k - len(ranked_project)]

    vector_matches = []
    try:
        memory_manager = MemoryManager(user_id=user_id)
        vector_matches = memory_manager.query_memory(query, scope="user", n_results=3)
    except Exception:
        vector_matches = []

    return {
        "project_facts": ranked_project,
        "user_facts": ranked_user,
        "vector_matches": vector_matches,
    }


def build_memory_injection_block(
    user_id: int,
    conversation_id: str,
    query: str,
    *,
    project_key: Optional[str] = None,
    max_chars: int = 1800,
) -> str:
    retrieved = retrieve_relevant_memory(user_id, query, project_key=project_key, top_k=7)
    session = get_session_memory(user_id, conversation_id)

    lines = ["=== HYBRID MEMORY CONTEXT ==="]
    if session:
        lines.append("Session memory:")
        lines.append(f"- summary: {session.get('summary', '')}")
        for note in session.get("key_notes", [])[:5]:
            lines.append(f"- note: {note}")

    if retrieved["project_facts"]:
        lines.append("Project facts:")
        for fact in retrieved["project_facts"]:
            source = fact.get("source", {})
            lines.append(
                f"- {fact.get('key')}: {fact.get('value')} "
                f"[source: convo={source.get('conversation_id')} msg={source.get('message_index')}]"
            )

    if retrieved["user_facts"]:
        lines.append("User facts:")
        for fact in retrieved["user_facts"]:
            source = fact.get("source", {})
            lines.append(
                f"- {fact.get('key')}: {fact.get('value')} "
                f"[source: convo={source.get('conversation_id')} msg={source.get('message_index')}]"
            )

    if retrieved["vector_matches"]:
        lines.append("Semantic memory matches:")
        for match in retrieved["vector_matches"][:3]:
            meta = match.get("metadata", {})
            lines.append(
                f"- {match.get('content')} "
                f"[source: convo={meta.get('conversation_id')} ts={meta.get('timestamp')}]"
            )

    lines.append("=== END HYBRID MEMORY CONTEXT ===")
    block = "\n".join(lines)
    return block[:max_chars]
