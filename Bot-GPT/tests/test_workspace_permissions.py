import os
import json
import uuid
import shutil
import pytest
from app import create_app
from models import User, _save_users, save_conversation
from tools import get_workspace_path

@pytest.fixture(scope='module')
def app():
    """Create and configure a new app instance for each test module."""
    app = create_app('testing')
    # Clean up instance folder before tests
    instance_path = app.instance_path
    if os.path.exists(instance_path):
        shutil.rmtree(instance_path)
    os.makedirs(instance_path)
    yield app
    # Clean up after tests
    if os.path.exists(instance_path):
        shutil.rmtree(instance_path)

@pytest.fixture(scope='module')
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture(scope='function')
def two_users(app):
    """Create two users in the users.json file."""
    with app.app_context():
        user1 = User(id=1, username='testuser1', password_hash=None)
        user1.set_password('password')
        user2 = User(id=2, username='testuser2', password_hash=None)
        user2.set_password('password')
        users = {
            '1': user1.to_dict(),
            '2': user2.to_dict()
        }
        _save_users(users)
        yield user1, user2

def login(client, username, password):
    return client.post('/login', json={'username': username, 'password': password})

def logout(client):
    return client.get('/logout')

def test_workspace_access_denied(client, app, two_users):
    user1, user2 = two_users

    # User 1 creates a conversation and a file
    with app.app_context():
        convo_id = str(uuid.uuid4())
        convo_data = {
            "id": convo_id, "owner_id": user1.id, "title": "User 1's Convo",
            "participants": [{"user_id": user1.id, "role": "owner"}], "messages": []
        }
        save_conversation(user1.id, convo_id, convo_data)

        workspace_path = get_workspace_path(convo_id, user1.id)
        with open(os.path.join(workspace_path, 'testfile.txt'), 'w') as f:
            f.write('hello')

    # User 2 tries to access User 1's file
    login(client, 'testuser2', 'password')
    response = client.get(f'/api/workspace/file?path=testfile.txt&conversation_id={convo_id}')
    assert response.status_code == 403
    assert 'Access denied' in response.json['error']
    logout(client)

    # User 1 (the owner) should be able to access the file
    login(client, 'testuser1', 'password')
    response = client.get(f'/api/workspace/file?path=testfile.txt&conversation_id={convo_id}')
    assert response.status_code == 200
    assert 'hello' in response.json['content']
    logout(client)

def test_participant_can_access_shared_conversation_file(client, app, two_users):
    user1, user2 = two_users
    convo_id = str(uuid.uuid4())

    # User 1 creates a conversation and a file
    with app.app_context():
        convo_data = {
            "id": convo_id, "owner_id": user1.id, "title": "Shared Convo",
            "participants": [{"user_id": user1.id, "role": "owner"}], "messages": []
        }
        save_conversation(user1.id, convo_id, convo_data)
        workspace_path = get_workspace_path(convo_id, user1.id)
        with open(os.path.join(workspace_path, 'sharedfile.txt'), 'w') as f:
            f.write('shared content')

    # User 1 shares the conversation with User 2 via API
    login(client, 'testuser1', 'password')
    share_response = client.post(f'/api/conversation/{convo_id}/share', json={'user_id': user2.id})
    assert share_response.status_code == 201
    logout(client)

    # User 2 (the participant) should now be able to access the file
    login(client, 'testuser2', 'password')
    response = client.get(f'/api/workspace/file?path=sharedfile.txt&conversation_id={convo_id}')

    assert response.status_code == 200
    assert 'shared content' in response.json['content']
    logout(client)
