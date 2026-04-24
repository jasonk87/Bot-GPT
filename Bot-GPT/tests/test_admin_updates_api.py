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
