import os
import uuid

from artifacts import list_artifacts_for_conversation
from models import save_conversation, add_to_conversation_index, add_user_to_conversation_index
from tools.file_system import write_file


def login(client, username, password):
    return client.post('/login', json={'username': username, 'password': password}, follow_redirects=True)


def _seed_conversation(app, user_id, convo_id):
    convo_path = os.path.join(app.instance_path, str(user_id), 'conversations', f'{convo_id}.json')
    save_conversation(convo_path, {
        "id": convo_id,
        "owner_id": user_id,
        "title": "Artifacts",
        "participants": [{"user_id": user_id, "role": "owner"}],
        "messages": [],
        "artifacts": [],
        "artifact_versions": {},
        "last_active_artifact_id": None,
    })
    add_to_conversation_index(os.path.join(app.instance_path, 'conversation_index.json'), convo_id, user_id)
    add_user_to_conversation_index(os.path.join(app.instance_path, 'user_conversation_index.json'), user_id, convo_id)


def test_artifact_metadata_persisted_on_create_and_update(client, app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
    login(client, test_user.username, 'password')

    create_resp = client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "utils.py",
        "content": "print('hi')",
    })
    assert create_resp.status_code == 200

    update_resp = client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "utils.py",
        "content": "print('hello')",
    })
    assert update_resp.status_code == 200

    artifacts_resp = client.get(f'/api/conversation/{convo_id}/artifacts')
    assert artifacts_resp.status_code == 200
    payload = artifacts_resp.get_json()
    assert len(payload["artifacts"]) == 1
    assert payload["artifacts"][0]["artifact_id"] == "utils.py"
    assert payload["artifacts"][0]["artifact_type"] == "code"


def test_multiple_artifacts_tracked_without_duplicates(client, app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
    login(client, test_user.username, 'password')

    for path in ["a.md", "b.html", "a.md"]:
        resp = client.post('/api/workspace/file', json={
            "conversation_id": convo_id,
            "path": path,
            "content": "content",
        })
        assert resp.status_code == 200

    artifacts_resp = client.get(f'/api/conversation/{convo_id}/artifacts')
    data = artifacts_resp.get_json()
    ids = [a["artifact_id"] for a in data["artifacts"]]
    assert ids.count("a.md") == 1
    assert ids.count("b.html") == 1


def test_selecting_artifact_updates_active_state(client, app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
    login(client, test_user.username, 'password')

    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "selected.txt",
        "content": "picked",
    })
    save_resp = client.post(f'/api/conversation/{convo_id}/artifacts', json={"artifact_id": "selected.txt"})
    assert save_resp.status_code == 200

    fetch_resp = client.get(f'/api/conversation/{convo_id}/artifacts')
    payload = fetch_resp.get_json()
    assert payload["last_active_artifact_id"] == "selected.txt"


def test_rename_and_delete_update_artifact_entries(client, app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
    login(client, test_user.username, 'password')

    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "old_name.py",
        "content": "print(1)",
    })
    rename_resp = client.post('/api/workspace/rename', json={
        "conversation_id": convo_id,
        "old_path": "old_name.py",
        "new_path": "new_name.py",
    })
    assert rename_resp.status_code == 200

    artifacts_after_rename = client.get(f'/api/conversation/{convo_id}/artifacts').get_json()["artifacts"]
    assert any(a["artifact_id"] == "new_name.py" for a in artifacts_after_rename)
    assert not any(a["artifact_id"] == "old_name.py" for a in artifacts_after_rename)

    delete_resp = client.delete('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "new_name.py",
    })
    assert delete_resp.status_code == 200
    artifacts_after_delete = client.get(f'/api/conversation/{convo_id}/artifacts').get_json()["artifacts"]
    assert artifacts_after_delete == []


def test_list_artifacts_helper_handles_missing_data(app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
        artifacts = list_artifacts_for_conversation(test_user.id, convo_id)
    assert artifacts == []


def test_tool_write_file_persists_artifact_metadata(app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
        result = write_file("tool_output.md", "# hi", convo_id, test_user.id)
        assert result["status"] == "file_written"
        artifacts = list_artifacts_for_conversation(test_user.id, convo_id)
        assert len(artifacts) == 1
        assert artifacts[0]["artifact_id"] == "tool_output.md"
        assert artifacts[0]["artifact_type"] == "markdown"


def test_version_created_on_update_and_retrievable(client, app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
    login(client, test_user.username, 'password')

    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "versioned.py",
        "content": "print('v1')",
    })
    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "versioned.py",
        "content": "print('v2')",
    })

    versions_resp = client.get(f'/api/artifact/versioned.py/versions?conversation_id={convo_id}')
    assert versions_resp.status_code == 200
    versions = versions_resp.get_json()["versions"]
    assert len(versions) == 1
    version_id = versions[0]["version_id"]

    detail_resp = client.get(f'/api/artifact/versioned.py/version/{version_id}?conversation_id={convo_id}')
    assert detail_resp.status_code == 200
    assert detail_resp.get_json()["content"] == "print('v1')"


def test_restore_version_updates_content_and_creates_new_version_entry(client, app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
    login(client, test_user.username, 'password')

    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "restore.py",
        "content": "print('one')",
    })
    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "restore.py",
        "content": "print('two')",
    })
    versions_before = client.get(f'/api/artifact/restore.py/versions?conversation_id={convo_id}').get_json()["versions"]
    original_version_id = versions_before[0]["version_id"]
    assert len(versions_before) == 1

    restore_resp = client.post(f'/api/artifact/restore.py/version/{original_version_id}/restore', json={
        "conversation_id": convo_id,
    })
    assert restore_resp.status_code == 200

    current_file_resp = client.get(f'/api/workspace/file?path=restore.py&conversation_id={convo_id}')
    assert current_file_resp.status_code == 200
    assert current_file_resp.get_json()["content"] == "print('one')"

    versions_after = client.get(f'/api/artifact/restore.py/versions?conversation_id={convo_id}').get_json()["versions"]
    assert len(versions_after) == 2
    assert versions_after[0]["content"] == "print('two')"
    assert versions_after[1]["content"] == "print('one')"


def test_rename_maintains_version_chain(client, app, test_user):
    convo_id = str(uuid.uuid4())
    with app.app_context():
        _seed_conversation(app, test_user.id, convo_id)
    login(client, test_user.username, 'password')

    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "chain.py",
        "content": "print('a')",
    })
    client.post('/api/workspace/file', json={
        "conversation_id": convo_id,
        "path": "chain.py",
        "content": "print('b')",
    })
    rename_resp = client.post('/api/workspace/rename', json={
        "conversation_id": convo_id,
        "old_path": "chain.py",
        "new_path": "chain_renamed.py",
    })
    assert rename_resp.status_code == 200

    old_versions_resp = client.get(f'/api/artifact/chain.py/versions?conversation_id={convo_id}')
    new_versions_resp = client.get(f'/api/artifact/chain_renamed.py/versions?conversation_id={convo_id}')
    assert old_versions_resp.get_json()["versions"] == []
    assert len(new_versions_resp.get_json()["versions"]) == 1
