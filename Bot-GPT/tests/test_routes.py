from unittest.mock import Mock
import os
from models import get_all_conversations_for_user
from shared_paths import get_users_path
from models import _load_users, _save_users, User

def test_index_route(client):
    """Test the main index route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'BotGPT Workspace' in response.data

def test_profile_route_unauthenticated(client):
    """Test that the profile route requires login."""
    with client.session_transaction() as sess:
        sess.clear()
    client.delete_cookie("session")
    client.delete_cookie("remember_token")
    response = client.get('/profile')
    assert response.status_code == 302 # Redirect to login
    assert "/login" in response.headers.get("Location", "")

def test_profile_route_authenticated(logged_in_client, test_user, app):
    """Test the profile route for an authenticated user."""
    with app.app_context():
        # Create some dummy conversations for the user
        from models import save_conversation, add_to_conversation_index, add_user_to_conversation_index
        import os
        convo_id = 'convo1'
        convo_path = os.path.join(app.instance_path, str(test_user.id), 'conversations', f'{convo_id}.json')
        save_conversation(convo_path, {'id': convo_id, 'owner_id': test_user.id, 'title': 'Test Convo 1', 'participants': [{'user_id': test_user.id, 'role': 'owner'}], 'messages': []})

        index_path = os.path.join(app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, convo_id, test_user.id)
        user_convo_index_path = os.path.join(app.instance_path, 'user_conversation_index.json')
        add_user_to_conversation_index(user_convo_index_path, test_user.id, convo_id)

        response = logged_in_client.get('/profile')
        assert response.status_code == 200
        assert b'BotGPT Profile' in response.data
        assert b'Test Convo 1' in response.data

def test_auth_routes(client, test_user, app):
    """Test registration and login routes."""
    # Test registering a new user
    import time
    unique_username = f"newuser_{time.time()}"
    register_rv = client.post('/register', json={'username': unique_username, 'password': 'newpassword'})
    assert register_rv.status_code == 201

    # Test logging in as the new user
    new_login_rv = client.post('/login', json={'username': unique_username, 'password': 'newpassword'})
    assert new_login_rv.status_code == 200

def test_get_models_api(logged_in_client, mocker):
    """Test the API endpoint for getting Ollama models."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {"name": "model1:latest"},
            {"name": "model2:latest"}
        ]
    }
    mocker.patch('requests.get', return_value=mock_response)

    response = logged_in_client.get('/api/models')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]['name'] == 'model1:latest'


def test_settings_include_and_persist_response_mode(logged_in_client, test_user):
    response = logged_in_client.get('/api/settings')
    assert response.status_code == 200
    settings = response.get_json()
    assert settings.get('response_mode_preference') == 'auto'
    assert settings.get('thought_panel_expanded') is False

    update = logged_in_client.post('/api/settings', json={'response_mode_preference': 'deep', 'thought_panel_expanded': True})
    assert update.status_code == 200

    settings_after = logged_in_client.get('/api/settings')
    assert settings_after.status_code == 200
    assert settings_after.get_json().get('response_mode_preference') == 'deep'
    assert settings_after.get_json().get('thought_panel_expanded') is True

    users = _load_users(get_users_path())
    saved_user = users.get(str(test_user.id), {})
    assert saved_user.get('response_mode_preference') == 'deep'
    assert saved_user.get('thought_panel_expanded') is True


def test_settings_include_and_persist_github_username(logged_in_client, test_user):
    response = logged_in_client.get('/api/settings')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload.get('github_username') == ''
    assert payload.get('is_admin') is True

    update = logged_in_client.post('/api/settings', json={'github_username': 'octocat'})
    assert update.status_code == 200

    settings_after = logged_in_client.get('/api/settings')
    assert settings_after.status_code == 200
    assert settings_after.get_json().get('github_username') == 'octocat'

    users = _load_users(get_users_path())
    saved_user = users.get(str(test_user.id), {})
    assert saved_user.get('github_username') == 'octocat'


def test_depth_metrics_endpoint_returns_json(logged_in_client):
    response = logged_in_client.get('/api/depth_metrics')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict)


def test_dependency_health_endpoint(client):
    response = client.get('/health/dependencies')
    assert response.status_code == 200
    data = response.get_json()
    assert data.get('status') in {'ok', 'degraded'}
    assert isinstance(data.get('required'), dict)
    assert isinstance(data.get('optional'), dict)


def test_health_endpoint_includes_degraded_mode_flag(client):
    response = client.get('/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data.get('status') in {'ok', 'degraded'}
    assert isinstance(data.get('degraded_mode'), bool)


def test_settings_tab_ownership_and_mobile_layout_markers(client):
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'settings-tabs-scroll' in html
    assert 'settings-content-scroll' in html
    assert 'settings-modal-shell' in html
    assert 'w-[calc(100vw-24px)]' in html
    assert 'overflow-x-hidden' in html
    assert 'settings-footer-actions' in html
    assert 'Default chat model' in html
    assert 'Deep chat model' in html
    assert 'Utility model' in html

    assert html.count('telegram-pair-btn') == 1
    assert html.count('telegram-unpair-btn') == 1
    assert html.count('workflow-refresh-btn') == 1
    assert html.count('workflow-list') == 1
    assert 'Telegram pairing is managed from this tab via Proactive panel controls.' not in html
    assert 'Learned workflows are available in the Proactive tab.' not in html

    assert 'admin-update-current-branch' in html
    assert 'admin-update-newest-branch' in html
    assert 'admin-update-history' in html
    assert 'admin-update-live-status' in html
    assert 'admin-update-live-step' in html
    assert 'admin-update-live-error' in html
    assert 'mobile-fullscreen' in html
    assert 'admin-update-status-panel' in html


def test_admin_updates_tab_visibility_flag_for_non_admin(client, app):
    with app.app_context():
        users_path = get_users_path()
        user = User(id=2, username='nonadmin', password_hash=None)
        user.set_password('password')
        _save_users(users_path, {'2': user.to_dict()})
    with client.session_transaction() as sess:
        sess['_user_id'] = '2'
        sess['_fresh'] = True

    response = client.get('/api/settings')
    assert response.status_code == 200
    assert response.get_json().get('is_admin') is False


def test_settings_is_admin_true_when_username_matches_admin_list(client, app):
    with app.app_context():
        app.config['ADMIN_USER_IDS'] = []
        app.config['ADMIN_USERNAMES'] = ['jason']
        users_path = get_users_path()
        user = User(id=7, username='Jason', password_hash=None)
        user.set_password('password')
        _save_users(users_path, {'7': user.to_dict()})
    with client.session_transaction() as sess:
        sess['_user_id'] = '7'
        sess['_fresh'] = True

    response = client.get('/api/settings')
    assert response.status_code == 200
    assert response.get_json().get('is_admin') is True


def test_existing_non_id_1_admin_username_sees_admin_updates_flag(client, app):
    with app.app_context():
        app.config['ADMIN_USER_IDS'] = [1]
        app.config['ADMIN_USERNAMES'] = ['jasonk87']
        users_path = get_users_path()
        user = User(id=42, username='jasonk87', password_hash=None)
        user.set_password('password')
        _save_users(users_path, {'42': user.to_dict()})
    with client.session_transaction() as sess:
        sess['_user_id'] = '42'
        sess['_fresh'] = True

    response = client.get('/api/settings')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload.get('is_admin') is True


def test_admin_updates_frontend_wires_check_and_apply_apis():
    with open('Bot-GPT/static/js/main.js', 'r', encoding='utf-8') as handle:
        script = handle.read()
    assert '/admin/updates/check' in script
    assert '/admin/updates/update' in script
    assert 'startAdminUpdatePolling' in script
    assert 'ADMIN_UPDATE_TERMINAL_STATES' in script
    assert 'Update in progress…' in script
    assert 'branch: adminUpdateBranchSelect.value' in script


def test_frontend_has_mobile_canvas_fullscreen_guards():
    with open('Bot-GPT/static/js/main.js', 'r', encoding='utf-8') as handle:
        script = handle.read()
    with open('Bot-GPT/templates/index.html', 'r', encoding='utf-8') as handle:
        html = handle.read()
    assert "canvasPanel.classList.toggle" in script
    assert "document.body.classList.toggle" in script
    assert "Back to Chat" in script
    assert '#file-viewer, #artifact-preview, #workspace-panel' in html


def test_os_safety_status_endpoint_returns_flags(logged_in_client):
    response = logged_in_client.get('/api/os-approvals/status')
    assert response.status_code == 200
    payload = response.get_json()
    assert 'os_agent_enabled' in payload
    assert 'os_agent_safe_mode' in payload


def test_attachment_view_endpoint_blocks_outside_paths(logged_in_client):
    response = logged_in_client.get('/api/attachments/view?path=/etc/passwd')
    assert response.status_code == 403


def test_attachment_view_endpoint_serves_allowed_user_file(logged_in_client, app, test_user):
    target_dir = os.path.join(app.instance_path, str(test_user.id), 'conversations', 'c1')
    os.makedirs(target_dir, exist_ok=True)
    image_path = os.path.join(target_dir, 'x.png')
    with open(image_path, 'wb') as handle:
        handle.write(b'png')
    response = logged_in_client.get(f'/api/attachments/view?path={image_path}')
    assert response.status_code == 200
