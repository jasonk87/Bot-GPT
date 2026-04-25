from typing import Dict, List


def estimate_context_usage(messages: List[Dict[str, str]], max_chars: int = 48000) -> float:
    # Increased max_chars to avoid excessive truncation of context leading to memory loss
    total = sum(len((message.get("content") or "")) for message in messages or [])
    return total / max_chars if max_chars else 0.0


def compact_session_history(messages: List[Dict[str, str]], keep_recent: int = 8) -> Dict[str, object]:
    if not messages:
        return {"summary": "", "key_notes": [], "trimmed_messages": []}

    older = messages[:-keep_recent] if len(messages) > keep_recent else []
    recent = messages[-keep_recent:] if len(messages) > keep_recent else list(messages)

    user_goals = []
    unresolved = []
    for message in older:
        content = (message.get("content") or "").strip()
        if not content:
            continue
        if message.get("role") == "user":
            user_goals.append(content[:160])
        if "todo:" in content.lower():
            unresolved.append(content[:160])

    summary_parts = []
    if user_goals:
        summary_parts.append(f"Earlier user goals: {' | '.join(user_goals[:3])}")
    if unresolved:
        summary_parts.append(f"Unresolved tasks: {' | '.join(unresolved[:3])}")
    summary = " ".join(summary_parts).strip()

    return {
        "summary": summary,
        "key_notes": (user_goals[:4] + unresolved[:4])[:8],
        "trimmed_messages": recent,
    }
