"""Verification helpers for benchmark answer quality checks."""

from __future__ import annotations


def verify_answer(answer: str, task: dict) -> dict:
    lower = answer.lower()
    expected_keywords = task.get("expected_keywords", [])
    matched = [kw for kw in expected_keywords if kw.lower() in lower]
    keyword_recall = (len(matched) / len(expected_keywords)) if expected_keywords else 1.0

    checks = []

    min_keyword_recall = float(task.get("min_keyword_recall", 0.5 if expected_keywords else 0.0))
    checks.append({
        "name": "keyword_recall",
        "passed": keyword_recall >= min_keyword_recall,
        "actual": round(keyword_recall, 3),
        "expected": f">= {min_keyword_recall}",
    })

    require_next_step = bool(task.get("require_next_step", True))
    if require_next_step:
        has_next_step = "next step:" in lower
        checks.append({
            "name": "next_step_present",
            "passed": has_next_step,
            "actual": has_next_step,
            "expected": True,
        })

    forbidden_patterns = task.get("forbidden_patterns", [])
    for pattern in forbidden_patterns:
        present = pattern.lower() in lower
        checks.append({
            "name": f"forbidden:{pattern}",
            "passed": not present,
            "actual": present,
            "expected": False,
        })

    passed = all(check["passed"] for check in checks)
    return {
        "passed": passed,
        "checks": checks,
        "matched_keywords": matched,
        "keyword_recall": round(keyword_recall, 3),
    }
