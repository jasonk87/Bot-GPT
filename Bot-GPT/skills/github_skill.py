import os
import subprocess
from typing import Any, Dict, List, Optional

from repo_index import (
    discover_local_repositories,
    load_repo_index,
    select_repository,
    get_selected_repository,
    extract_repo_metadata,
)


def _read_file(repo_path: str, rel_path: str, max_bytes: int = 500_000) -> str:
    file_path = os.path.abspath(os.path.join(repo_path, rel_path))
    if not file_path.startswith(os.path.abspath(repo_path)):
        return "Error: Access denied."
    if not os.path.isfile(file_path):
        return "Error: File not found."
    with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read(max_bytes)


def _recent_commits(repo_path: str, limit: int = 5) -> List[Dict[str, str]]:
    process = subprocess.run(
        ["git", "log", f"-{max(1, min(limit, 20))}", "--pretty=format:%H|%ct|%s"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if process.returncode != 0:
        return []
    commits = []
    for line in process.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        commits.append({"sha": parts[0], "timestamp": parts[1], "message": parts[2]})
    return commits


def github_skill(
    action: str,
    repo: Optional[str] = None,
    path: Optional[str] = None,
    base_paths: Optional[List[str]] = None,
    limit: int = 5,
    conversation_id: Optional[str] = None,
    owner_id: Optional[int] = None,
    **_kwargs,
) -> Dict[str, Any]:
    """
    High-level repo intelligence skill.
    Supported actions:
    - discover_repos
    - list_repos
    - analyze_repo
    - select_repo
    - read_repo_file
    - recent_commits
    """
    if not owner_id:
        return {"status": "error", "error": "owner_id is required"}

    normalized_action = (action or "").strip().lower()
    if normalized_action == "discover_repos":
        index = discover_local_repositories(owner_id, base_paths=base_paths)
        status = index.get("status", "success")
        if status in {"blocked", "error"}:
            return {
                "status": status,
                "error": index.get("error"),
                "repos": index.get("repos", []),
                "selected_repo_path": index.get("selected_repo_path"),
            }
        return {"status": "success", "repos": index.get("repos", []), "selected_repo_path": index.get("selected_repo_path")}

    if normalized_action == "list_repos":
        index = load_repo_index(owner_id)
        return {"status": "success", "repos": index.get("repos", []), "selected_repo_path": index.get("selected_repo_path")}

    if normalized_action == "select_repo":
        if not repo:
            return {"status": "error", "error": "repo is required"}
        selected = select_repository(owner_id, repo)
        if not selected:
            return {"status": "error", "error": f"Repo '{repo}' not found in index."}
        return {
            "status": "repo_selected",
            "repo": selected,
            "entry_point": selected.get("preferred_preview_target"),
            "conversation_id": conversation_id,
        }

    selected_repo = None
    if repo:
        index = load_repo_index(owner_id)
        selected_repo = next((r for r in index.get("repos", []) if r.get("name") == repo or r.get("path") == repo), None)
    if not selected_repo:
        selected_repo = get_selected_repository(owner_id)
    if not selected_repo:
        return {"status": "error", "error": "No repo selected. Run discover_repos then select_repo first."}

    repo_path = selected_repo["path"]
    if normalized_action == "analyze_repo":
        return {"status": "success", "repo": extract_repo_metadata(repo_path)}
    if normalized_action == "read_repo_file":
        if not path:
            return {"status": "error", "error": "path is required"}
        return {"status": "success", "path": path, "content": _read_file(repo_path, path)}
    if normalized_action == "recent_commits":
        return {"status": "success", "repo": selected_repo.get("name"), "commits": _recent_commits(repo_path, limit=limit)}

    return {"status": "error", "error": f"Unsupported github_skill action '{action}'"}
