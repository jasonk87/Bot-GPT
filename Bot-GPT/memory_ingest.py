import re
from typing import Dict, List


_NOISE_PATTERNS = [
    re.compile(r"^(hi|hello|thanks|ok|okay|cool)[!. ]*$", re.IGNORECASE),
    re.compile(r".*ai cannot access desktop.*", re.IGNORECASE),
    re.compile(r".*ml learning: depends on effort.*", re.IGNORECASE),
    re.compile(r".*user name revealed.*", re.IGNORECASE),
    re.compile(r".*unknown user's name requested.*", re.IGNORECASE),
]


def is_memory_worthy(text: str) -> bool:
    if not text or len(text.strip()) < 8:
        return False
    if any(pattern.match(text.strip()) for pattern in _NOISE_PATTERNS):
        return False
    lowered = text.lower()
    if lowered.startswith("assistant:") or lowered.startswith("system:"):
        return False
    signals = [
        "i prefer",
        "remember",
        "i use",
        "my name is",
        "call me",
        "i am ",
        "my repo",
        "project",
        "we decided",
        "resolved",
        "root cause",
        "architecture",
        "working on",
    ]
    return any(signal in lowered for signal in signals)


def extract_facts_from_message(content: str) -> List[Dict[str, object]]:
    if not is_memory_worthy(content):
        return []
    text = content.strip()
    facts: List[Dict[str, object]] = []
    lowered = text.lower()

    pref_match = re.search(r"i prefer ([^.,;]+)", lowered)
    if pref_match:
        pref = pref_match.group(1).strip()
        facts.append({
            "scope": "user",
            "key": f"preference:{pref}",
            "value": f"User prefers {pref}.",
            "confidence": 0.85,
        })

    name_match = re.search(r"\bmy name is\s+([a-zA-Z][a-zA-Z0-9 _'-]{0,40})", text, re.IGNORECASE)
    if name_match:
        display_name = name_match.group(1).strip()
        facts.append({
            "scope": "user",
            "key": "identity:name",
            "value": display_name,
            "confidence": 0.95,
        })

    call_me_match = re.search(r"\bcall me\s+([a-zA-Z][a-zA-Z0-9 _'-]{0,40})", text, re.IGNORECASE)
    if call_me_match:
        display_name = call_me_match.group(1).strip()
        facts.append({
            "scope": "user",
            "key": "identity:display_name",
            "value": display_name,
            "confidence": 0.95,
        })

    project_match = re.search(r"(project|repo)\s+([a-zA-Z0-9._-]+)", text)
    if project_match:
        name = project_match.group(2)
        facts.append({
            "scope": "project",
            "key": f"project_ref:{name}",
            "value": f"User referenced project/repo {name}.",
            "confidence": 0.75,
        })

    decision_match = re.search(r"(we decided|decision):?\s*(.+)", lowered)
    if decision_match:
        decision = decision_match.group(2).strip()
        facts.append({
            "scope": "project",
            "key": f"decision:{decision[:40]}",
            "value": decision,
            "confidence": 0.8,
        })

    if not facts:
        facts.append({
            "scope": "user",
            "key": f"note:{hash(text) % 10_000_000}",
            "value": text[:300],
            "confidence": 0.6,
        })
    return facts[:4]
