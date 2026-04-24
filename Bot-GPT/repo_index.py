import os
import json
import time
import subprocess
from collections import Counter
from typing import Dict, List, Optional

from flask import current_app
from repo_analyzer import detect_entry_points, analyze_repo_structure, rank_repositories


IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def _repo_index_path(owner_id) -> str:
    return os.path.join(current_app.instance_path, str(owner_id), "project_index.json")


def load_repo_index(owner_id) -> Dict[str, object]:
    path = _repo_index_path(owner_id)
    if not os.path.exists(path):
        return {"repos": [], "selected_repo_path": None, "updated_at": None}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"repos": [], "selected_repo_path": None, "updated_at": None}


def save_repo_index(owner_id, index_data: Dict[str, object]) -> None:
    path = _repo_index_path(owner_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(index_data, handle, indent=2)


def _guess_primary_languages(repo_path: str, file_samples: int = 2000) -> List[str]:
    ext_counter = Counter()
    seen = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for filename in files:
            seen += 1
            if seen > file_samples:
                break
            ext = os.path.splitext(filename)[1].lower()
            if ext:
                ext_counter[ext] += 1
        if seen > file_samples:
            break
    ext_to_lang = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".jsx": "JavaScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".rb": "Ruby",
        ".php": "PHP",
        ".html": "HTML",
        ".css": "CSS",
    }
    langs = [ext_to_lang.get(ext, ext) for ext, _ in ext_counter.most_common(3)]
    return langs


def _presence_flags(repo_path: str) -> Dict[str, bool]:
    return {
        "has_readme": any(os.path.isfile(os.path.join(repo_path, f)) for f in ["README.md", "README.rst", "README.txt"]),
        "has_tests": any(os.path.exists(os.path.join(repo_path, folder)) for folder in ["tests", "test"]),
        "has_python_config": any(os.path.isfile(os.path.join(repo_path, f)) for f in ["requirements.txt", "pyproject.toml", "setup.py"]),
        "has_js_config": any(os.path.isfile(os.path.join(repo_path, f)) for f in ["package.json", "pnpm-lock.yaml", "yarn.lock"]),
        "has_build_config": any(os.path.isfile(os.path.join(repo_path, f)) for f in ["Makefile", "Dockerfile", "docker-compose.yml", "tsconfig.json"]),
    }


def _file_stats(repo_path: str) -> Dict[str, int]:
    file_count = 0
    total_size = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for filename in files:
            file_count += 1
            full_path = os.path.join(root, filename)
            try:
                total_size += os.path.getsize(full_path)
            except OSError:
                continue
    return {"file_count": file_count, "size_bytes": total_size}


def _last_commit_timestamp(repo_path: str) -> Optional[float]:
    try:
        process = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if process.returncode == 0 and process.stdout.strip().isdigit():
            return float(process.stdout.strip())
    except Exception:
        return None
    return None


def extract_repo_metadata(repo_path: str) -> Dict[str, object]:
    stats = _file_stats(repo_path)
    metadata = {
        "name": os.path.basename(repo_path.rstrip("/")),
        "path": repo_path,
        "last_modified_time": os.path.getmtime(repo_path),
        "last_commit_time": _last_commit_timestamp(repo_path),
        "primary_languages": _guess_primary_languages(repo_path),
        "file_count": stats["file_count"],
        "size_bytes": stats["size_bytes"],
        "presence_flags": _presence_flags(repo_path),
        "entry_points": detect_entry_points(repo_path),
    }
    metadata.update(analyze_repo_structure(metadata))
    return metadata


def discover_local_repositories(owner_id, base_paths: Optional[List[str]] = None, max_depth: int = 4) -> Dict[str, object]:
    default_paths = [
        current_app.instance_path,
        current_app.config.get("USER_DATA_DIR"),
        os.path.expanduser("~"),
    ]
    roots = [path for path in (base_paths or default_paths) if isinstance(path, str) and os.path.isdir(path)]
    discovered = []
    seen = set()

    for root in roots:
        for current_root, dirs, _files in os.walk(root):
            rel_depth = os.path.relpath(current_root, root).count(os.sep)
            if rel_depth > max_depth:
                dirs[:] = []
                continue
            if ".git" in dirs:
                repo_path = os.path.abspath(current_root)
                if repo_path in seen:
                    continue
                seen.add(repo_path)
                discovered.append(extract_repo_metadata(repo_path))
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

    ranked = rank_repositories(discovered)
    index = load_repo_index(owner_id)
    index["repos"] = ranked
    index["updated_at"] = time.time()
    if index.get("selected_repo_path") and index["selected_repo_path"] not in [repo["path"] for repo in ranked]:
        index["selected_repo_path"] = None
    save_repo_index(owner_id, index)
    return index


def select_repository(owner_id, repo_identifier: str) -> Optional[Dict[str, object]]:
    index = load_repo_index(owner_id)
    repos = index.get("repos") or []
    selected = next(
        (
            repo
            for repo in repos
            if repo.get("name") == repo_identifier or repo.get("path") == repo_identifier
        ),
        None,
    )
    if not selected:
        return None
    index["selected_repo_path"] = selected["path"]
    save_repo_index(owner_id, index)
    return selected


def get_selected_repository(owner_id) -> Optional[Dict[str, object]]:
    index = load_repo_index(owner_id)
    selected_path = index.get("selected_repo_path")
    for repo in index.get("repos", []):
        if repo.get("path") == selected_path:
            return repo
    return None
