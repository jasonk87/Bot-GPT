import json
import os
from typing import Dict, List


ENTRY_CANDIDATES = [
    "main.py",
    "app.py",
    "__main__.py",
    "manage.py",
    "index.html",
    "server.js",
    "src/main.py",
    "src/app.py",
    "src/index.ts",
    "src/index.js",
]


def detect_entry_points(repo_path: str) -> List[str]:
    found = []
    for candidate in ENTRY_CANDIDATES:
        full = os.path.join(repo_path, candidate)
        if os.path.isfile(full):
            found.append(candidate)

    package_json = os.path.join(repo_path, "package.json")
    if os.path.isfile(package_json):
        try:
            with open(package_json, "r", encoding="utf-8") as handle:
                package = json.load(handle)
            main_value = package.get("main")
            if isinstance(main_value, str) and main_value and os.path.isfile(os.path.join(repo_path, main_value)):
                if main_value not in found:
                    found.append(main_value)
            scripts = package.get("scripts", {})
            if isinstance(scripts, dict):
                if "start" in scripts:
                    found.append("package.json:scripts.start")
                if "dev" in scripts:
                    found.append("package.json:scripts.dev")
        except Exception:
            pass
    return found[:5]


def analyze_repo_structure(metadata: Dict[str, object]) -> Dict[str, object]:
    entry_points = metadata.get("entry_points") or []
    primary_languages = metadata.get("primary_languages") or []
    flags = metadata.get("presence_flags") or {}

    components = []
    if flags.get("has_tests"):
        components.append("tests")
    if flags.get("has_readme"):
        components.append("documentation")
    if flags.get("has_python_config"):
        components.append("python setup")
    if flags.get("has_js_config"):
        components.append("javascript setup")

    return {
        "summary": (
            f"Repo {metadata.get('name')} is primarily {', '.join(primary_languages[:2]) or 'mixed'} "
            f"with {metadata.get('file_count', 0)} files."
        ),
        "entry_points": entry_points,
        "major_components": components,
        "preferred_preview_target": entry_points[0] if entry_points else None,
    }


def rank_repositories(repositories: List[Dict[str, object]]) -> List[Dict[str, object]]:
    def score(repo: Dict[str, object]) -> float:
        freshness = float(repo.get("last_modified_time") or 0)
        complexity = float(repo.get("file_count") or 0)
        recent_commit = float(repo.get("last_commit_time") or 0)
        return (freshness * 0.6) + (recent_commit * 0.3) + (complexity * 0.1)

    ranked = sorted(repositories, key=score, reverse=True)
    return ranked
