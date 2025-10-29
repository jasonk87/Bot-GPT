import pytest
from flask import url_for
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
        save_conversation(test_user.id, 'convo1', {'id': 'convo1', 'owner_id': test_user.id, 'title': 'Test Convo 1', 'participants': [], 'messages': []})

        response = logged_in_client.get('/profile')
        assert response.status_code == 200
        assert b'User Profile' in response.data
        assert b'Test Convo 1' in response.data

def test_auth_routes(client, test_user, app):
    """Test registration and login routes."""
    # Note: test_user fixture already creates a user.
    # Here we can test the login for that user.
    login_rv = client.post('/login', json={'username': 'testuser', 'password': 'password'})
    assert login_rv.status_code == 200

    # Test logout
    logout_rv = client.get('/logout')
    assert logout_rv.status_code == 200

    # Test registering a new user
    register_rv = client.post('/register', json={'username': 'newuser', 'password': 'newpassword'})
    assert register_rv.status_code == 201

    # Test logging in as the new user
    new_login_rv = client.post('/login', json={'username': 'newuser', 'password': 'newpassword'})
    assert new_login_rv.status_code == 200
