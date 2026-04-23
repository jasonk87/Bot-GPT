import os

from repo_analyzer import detect_entry_points, analyze_repo_structure
from repo_index import (
    discover_local_repositories,
    extract_repo_metadata,
    save_repo_index,
    load_repo_index,
    select_repository,
)
from skills.github_skill import github_skill


def _make_repo(base_dir, name, files):
    repo_path = os.path.join(base_dir, name)
    os.makedirs(os.path.join(repo_path, ".git"), exist_ok=True)
    for rel, content in files.items():
        full = os.path.join(repo_path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(content)
    return repo_path


def test_repo_discovery_identifies_git_repositories(app, test_user, tmp_path):
    repo1 = _make_repo(tmp_path, "alpha", {"main.py": "print('x')", "README.md": "alpha"})
    _make_repo(tmp_path, "beta", {"app.py": "print('y')", "tests/test_app.py": "def test_ok(): assert True"})

    with app.app_context():
        index = discover_local_repositories(test_user.id, base_paths=[str(tmp_path)])
    names = {repo["name"] for repo in index["repos"]}
    assert "alpha" in names
    assert "beta" in names
    assert any(repo["path"] == str(repo1) for repo in index["repos"])


def test_metadata_extraction_returns_expected_fields(app, test_user, tmp_path):
    repo = _make_repo(tmp_path, "gamma", {"main.py": "print('g')", "requirements.txt": "flask"})
    with app.app_context():
        metadata = extract_repo_metadata(str(repo))
    assert metadata["name"] == "gamma"
    assert "primary_languages" in metadata
    assert "file_count" in metadata
    assert "presence_flags" in metadata
    assert "entry_points" in metadata


def test_entry_point_detection_common_patterns(tmp_path):
    repo = _make_repo(tmp_path, "delta", {"main.py": "print('d')", "src/app.py": "print('a')"})
    entry_points = detect_entry_points(str(repo))
    assert "main.py" in entry_points
    assert "src/app.py" in entry_points


def test_repo_analysis_produces_structured_summary():
    analysis = analyze_repo_structure({
        "name": "project-x",
        "primary_languages": ["Python"],
        "file_count": 42,
        "entry_points": ["app.py"],
        "presence_flags": {"has_tests": True, "has_readme": True, "has_python_config": True, "has_js_config": False},
    })
    assert "summary" in analysis
    assert analysis["preferred_preview_target"] == "app.py"
    assert "major_components" in analysis


def test_github_skill_routes_actions(app, test_user, tmp_path):
    repo = _make_repo(tmp_path, "epsilon", {"app.py": "print('e')"})
    with app.app_context():
        index = {"repos": [extract_repo_metadata(str(repo))], "selected_repo_path": None, "updated_at": None}
        save_repo_index(test_user.id, index)

        selected = github_skill("select_repo", repo="epsilon", owner_id=test_user.id)
        assert selected["status"] == "repo_selected"

        listed = github_skill("list_repos", owner_id=test_user.id)
        assert listed["status"] == "success"
        assert listed["repos"][0]["name"] == "epsilon"

        analyzed = github_skill("analyze_repo", owner_id=test_user.id)
        assert analyzed["status"] == "success"
        assert analyzed["repo"]["name"] == "epsilon"


def test_repo_selection_persists_context(app, test_user, tmp_path):
    repo = _make_repo(tmp_path, "zeta", {"main.py": "print('z')"})
    with app.app_context():
        save_repo_index(test_user.id, {"repos": [extract_repo_metadata(str(repo))], "selected_repo_path": None, "updated_at": None})
        selected = select_repository(test_user.id, "zeta")
        assert selected is not None
        loaded = load_repo_index(test_user.id)
    assert loaded["selected_repo_path"] == str(repo)
