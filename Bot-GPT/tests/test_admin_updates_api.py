import os
from unittest.mock import patch

from models import User, _save_users


def test_admin_updates_check_requires_admin(client, app):
    with app.app_context():
        users_path = os.path.join(app.instance_path, 'users.json')
        user = User(id=2, username='normal', password_hash=None)
        user.set_password('password')
        _save_users(users_path, {'2': user.to_dict()})
    with client.session_transaction() as sess:
        sess['_user_id'] = '2'
        sess['_fresh'] = True

    response = client.get('/api/admin/updates/check')
    assert response.status_code == 403
    assert response.get_json().get('error') == 'Access denied'


def test_admin_updates_check_refreshes_and_returns_state(logged_in_client, app):
    payload = {
        "status": "ready",
        "snapshot": {"branch": "work", "commit": "abc123", "dirty": False},
        "remote_branches": [{"name": "origin/main", "commit": "def456", "updated_at": "2026-01-01", "subject": "x"}],
        "newest_remote": {"name": "origin/main", "commit": "def456"},
        "last_checked": 1700000000.0,
    }
    with patch('workspace.update_manager.refresh', return_value=payload) as refresh:
        response = logged_in_client.get('/api/admin/updates/check')
    assert response.status_code == 200
    assert response.get_json().get('newest_remote', {}).get('name') == 'origin/main'
    refresh.assert_called_once_with(app.instance_path)


def test_admin_updates_check_accepts_username_admin(client, app):
    with app.app_context():
        app.config['ADMIN_USER_IDS'] = []
        app.config['ADMIN_USERNAMES'] = ['jason']
        users_path = os.path.join(app.instance_path, 'users.json')
        user = User(id=17, username='Jason', password_hash=None)
        user.set_password('password')
        _save_users(users_path, {'17': user.to_dict()})

    with client.session_transaction() as sess:
        sess['_user_id'] = '17'
        sess['_fresh'] = True

    with patch('workspace.update_manager.refresh', return_value={"status": "ready"}) as refresh:
        response = client.get('/api/admin/updates/check')

    assert response.status_code == 200
    assert response.get_json().get('status') == 'ready'
    refresh.assert_called_once_with(app.instance_path)


def test_admin_updates_apply_sends_full_branch_ref(logged_in_client, app):
    with patch('workspace.update_manager.is_state_fresh', return_value=True), \
         patch('workspace.update_manager.start_update', return_value={"status": "started"}) as start_update:
        response = logged_in_client.post('/api/admin/updates/update', json={
            "branch": "origin/feature/very-long-branch-name",
            "strategy": "abort",
        })
    assert response.status_code == 200
    kwargs = start_update.call_args.kwargs
    assert kwargs["branch"] == "origin/feature/very-long-branch-name"


def test_admin_updates_apply_returns_busy_for_double_submit(logged_in_client, app):
    with patch('workspace.update_manager.is_state_fresh', return_value=True), \
         patch('workspace.update_manager.start_update', return_value={"status": "busy", "message": "Update already in progress."}):
        response = logged_in_client.post('/api/admin/updates/update', json={
            "branch": "origin/main",
            "strategy": "abort",
        })
    assert response.status_code == 409
    assert response.get_json().get("status") == "busy"
