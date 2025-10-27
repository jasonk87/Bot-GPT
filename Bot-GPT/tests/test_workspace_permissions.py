import os
import pytest
from app import create_app, db
from models import User, Conversation, ConversationParticipant
from tools import get_workspace_path

@pytest.fixture(scope='module')
def app():
    """Create and configure a new app instance for each test module."""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture(scope='module')
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture(scope='function')
def two_users(app):
    """Create two users and log them in."""
    with app.app_context():
        user1 = User(username='testuser1')
        user1.set_password('password')
        user2 = User(username='testuser2')
        user2.set_password('password')
        db.session.add(user1)
        db.session.add(user2)
        db.session.commit()
        yield user1, user2
        db.session.delete(user1)
        db.session.delete(user2)
        db.session.commit()

def login(client, username, password):
    return client.post('/login', json={'username': username, 'password': password}, follow_redirects=True)

def logout(client):
    return client.get('/logout', follow_redirects=True)

def test_workspace_access_denied(client, app, two_users):
    user1, user2 = two_users

    # User 1 creates a conversation and a file
    with app.app_context():
        convo = Conversation(owner_id=user1.id, title="User 1's Convo")
        db.session.add(convo)
        db.session.commit()

        participant = ConversationParticipant(user_id=user1.id, conversation_id=convo.id, role='owner')
        db.session.add(participant)
        db.session.commit()

        workspace_path = get_workspace_path(convo.id, user1.id)
        os.makedirs(workspace_path, exist_ok=True)
        with open(os.path.join(workspace_path, 'testfile.txt'), 'w') as f:
            f.write('hello')

    # User 2 tries to access User 1's file
    login(client, 'testuser2', 'password')
    response = client.get(f'/api/workspace/file?path=testfile.txt&conversation_id={convo.id}')
    assert response.status_code == 403
    assert 'Access denied' in response.json['error']
    logout(client)

    # User 1 (the owner) should be able to access the file
    login(client, 'testuser1', 'password')
    response = client.get(f'/api/workspace/file?path=testfile.txt&conversation_id={convo.id}')
    assert response.status_code == 200
    assert 'hello' in response.json['content']
    logout(client)

def test_participant_can_access_shared_conversation_file(client, app, two_users):
    user1, user2 = two_users
    convo_id = None

    # User 1 creates a conversation and a file
    with app.app_context():
        convo = Conversation(owner_id=user1.id, title="User 1's Shared Convo")
        db.session.add(convo)
        db.session.commit()
        convo_id = convo.id

        # User 1 is the owner
        owner_participant = ConversationParticipant(user_id=user1.id, conversation_id=convo_id, role='owner')
        db.session.add(owner_participant)
        db.session.commit()

        workspace_path = get_workspace_path(convo_id, user1.id)
        os.makedirs(workspace_path, exist_ok=True)
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

    # This is the assertion that is likely to fail and will show the bug
    assert response.status_code == 200
    assert 'shared content' in response.json['content']
    logout(client)
