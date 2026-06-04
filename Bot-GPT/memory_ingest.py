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
        "you're ",
        "you are ",
        "your wife",
        "your sons",
        "you work",
        "you served",
        "you live",
        "you want to",
        "i am ",
        "my repo",
        "project",
        "major projects",
        "gaming preferences",
        "we decided",
        "resolved",
        "root cause",
        "architecture",
        "working on",
    ]
    return any(signal in lowered for signal in signals)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:50] or "note"


def _compact_lines(lines: List[str], limit: int = 900) -> str:
    text = " ".join(line.strip(" -\t") for line in lines if line.strip()).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit].rstrip()


def _extract_profile_sections(text: str) -> List[Dict[str, object]]:
    facts: List[Dict[str, object]] = []
    section_aliases = {
        "you": "profile:overview",
        "your job": "profile:job",
        "your family": "profile:family",
        "your personality": "profile:personality",
        "programming interests": "profile:programming_interests",
        "major projects you've worked on": "profile:major_projects",
        "gaming preferences": "profile:gaming_preferences",
        "goals you've mentioned": "profile:goals",
        "one pattern i've noticed": "profile:pattern",
    }
    current_heading = None
    current_lines: List[str] = []

    def flush_section():
        if not current_heading or not current_lines:
            return
        heading_key = section_aliases.get(current_heading.lower(), f"profile:{_slug(current_heading)}")
        value = _compact_lines(current_lines)
        if value:
            facts.append({
                "scope": "user",
                "key": heading_key,
                "value": value,
                "confidence": 0.82,
            })

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        looks_like_heading = (
            len(line) <= 45
            and not line.endswith(".")
            and not line.startswith(("-", "*", "•"))
            and line.lower() not in {"you've talked about:", "goals include:", "things you've added include:"}
            and not line.lower().startswith("your sons are")
        )
        if looks_like_heading and (
            line.lower() in section_aliases
            or line.startswith("Your ")
            or line in {"You", "Rumi", "Self-Evolving AI", "Living World / This-Is-Life", "OpenClaw"}
        ):
            flush_section()
            current_heading = line
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)
    flush_section()
    return facts


def _extract_sons(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    for idx, line in enumerate(lines):
        if not re.match(r"^your sons are:?\s*$", line, re.IGNORECASE):
            continue
        names = []
        for candidate in lines[idx + 1:]:
            if not candidate:
                continue
            if re.match(r"^(you('|’)ve|you have|your|you)\b", candidate, re.IGNORECASE):
                break
            if re.match(r"^[A-Z][a-zA-Z'-]{1,40}$", candidate):
                names.append(candidate)
                continue
            break
        return ", ".join(names)
    inline_match = re.search(r"\byour sons are:?\s*([A-Z][a-zA-Z'-]+)\s+and\s+([A-Z][a-zA-Z'-]+)", text, re.IGNORECASE)
    if inline_match:
        return f"{inline_match.group(1)}, {inline_match.group(2)}"
    return ""


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

    full_name_match = re.search(
        r"\b(?:you're|you are)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})(?=[,.;\n])",
        text,
        re.IGNORECASE,
    )
    if full_name_match:
        facts.append({
            "scope": "user",
            "key": "identity:name",
            "value": full_name_match.group(1).strip(),
            "confidence": 0.95,
        })

    wife_match = re.search(r"\byour wife is\s+([A-Z][a-zA-Z'-]{1,40})", text, re.IGNORECASE)
    if wife_match:
        facts.append({
            "scope": "user",
            "key": "family:wife",
            "value": wife_match.group(1).strip(),
            "confidence": 0.9,
        })

    sons = _extract_sons(text)
    if sons:
        facts.append({
            "scope": "user",
            "key": "family:sons",
            "value": sons,
            "confidence": 0.9,
        })

    job_match = re.search(r"\byou work in\s+([^.\n]+)", text, re.IGNORECASE)
    if job_match:
        facts.append({
            "scope": "user",
            "key": "work:field",
            "value": job_match.group(1).strip(),
            "confidence": 0.85,
        })

    role_match = re.search(r"\bGeneral Foreman for\s+([^.\n]+)", text, re.IGNORECASE)
    if role_match:
        facts.append({
            "scope": "user",
            "key": "work:role",
            "value": f"General Foreman for {role_match.group(1).strip()}",
            "confidence": 0.9,
        })

    location_match = re.search(r"\byou live in\s+([^.\n]+)", text, re.IGNORECASE)
    if location_match:
        facts.append({
            "scope": "user",
            "key": "identity:location",
            "value": location_match.group(1).strip(),
            "confidence": 0.85,
        })

    service_match = re.search(r"\byou served in the Army for\s+([^.\n]+)", text, re.IGNORECASE)
    if service_match:
        facts.append({
            "scope": "user",
            "key": "background:military_service",
            "value": f"Served in the Army for {service_match.group(1).strip()}",
            "confidence": 0.85,
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

    facts.extend(_extract_profile_sections(text))

    if not facts:
        facts.append({
            "scope": "user",
            "key": f"note:{hash(text) % 10_000_000}",
            "value": text[:900],
            "confidence": 0.6,
        })
    return facts[:30]
