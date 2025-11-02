from unittest.mock import Mock
from models import get_all_conversations_for_user

def test_index_route(client):
    """Test the main index route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'Ollama Agent' in response.data

def test_profile_route_unauthenticated(client):
    """Test that the profile route requires login."""
    response = client.get('/profile')
    assert response.status_code == 302 # Redirect to login

def test_profile_route_authenticated(logged_in_client, test_user, app):
    """Test the profile route for an authenticated user."""
    with app.app_context():
        # Create some dummy conversations for the user
        from models import save_conversation
        import os
        convo_path = os.path.join(app.instance_path, str(test_user.id), 'conversations', 'convo1.json')
        save_conversation(convo_path, {'id': 'convo1', 'owner_id': test_user.id, 'title': 'Test Convo 1', 'participants': [], 'messages': []})

        response = logged_in_client.get('/profile')
        assert response.status_code == 200
        assert b'User Profile' in response.data
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
