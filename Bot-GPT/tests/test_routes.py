from unittest.mock import Mock
from models import get_all_conversations_for_user
from shared_paths import get_users_path
from models import _load_users

def test_index_route(client):
    """Test the main index route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'BotGPT Workspace' in response.data

def test_profile_route_unauthenticated(client):
    """Test that the profile route requires login."""
    response = client.get('/profile')
    assert response.status_code == 302 # Redirect to login

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
