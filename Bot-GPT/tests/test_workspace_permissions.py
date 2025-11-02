
import os
import uuid
from models import save_conversation, add_to_conversation_index
from tools.file_system import get_workspace_path

def login(client, user):
    """Helper function to log in a user."""
    with client.session_transaction() as sess:
        sess['_user_id'] = user.id
        sess['_fresh'] = True

def test_workspace_access_denied(client, app, two_users):
    user1, user2 = two_users

    # User 1 creates a conversation and a file
    with app.app_context():
        convo_id = str(uuid.uuid4())
        convo_data = {
            "id": convo_id, "owner_id": user1.id, "title": "User 1's Convo",
            "participants": [{"user_id": user1.id, "role": "owner"}], "messages": []
        }
        convo_path = os.path.join(app.instance_path, str(user1.id), 'conversations', f'{convo_id}.json')
        save_conversation(convo_path, convo_data)
        index_path = os.path.join(app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, convo_id, user1.id)

        workspace_path = get_workspace_path(convo_id, user1.id)
        with open(os.path.join(workspace_path, 'testfile.txt'), 'w') as f:
            f.write('hello')

    # User 2 tries to access User 1's file
    login(client, user2)
    response = client.get(f'/api/workspace/file?path=testfile.txt&conversation_id={convo_id}')
    assert response.status_code == 403

def test_participant_can_access_shared_conversation_file(client, app, two_users):
    user1, user2 = two_users
    convo_id = str(uuid.uuid4())

    # User 1 creates a conversation and a file
    with app.app_context():
        convo_data = {
            "id": convo_id, "owner_id": user1.id, "title": "Shared Convo",
            "participants": [{"user_id": user1.id, "role": "owner"}], "messages": []
        }
        convo_path = os.path.join(app.instance_path, str(user1.id), 'conversations', f'{convo_id}.json')
        save_conversation(convo_path, convo_data)
        index_path = os.path.join(app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, convo_id, user1.id)
        workspace_path = get_workspace_path(convo_id, user1.id)
        with open(os.path.join(workspace_path, 'sharedfile.txt'), 'w') as f:
            f.write('shared content')

    # User 1 shares the conversation with User 2 via API
    login(client, user1)
    share_response = client.post(f'/api/conversation/{convo_id}/share', json={'user_id': user2.id})
    assert share_response.status_code == 201

    # User 2 (now a participant) tries to access the file
    login(client, user2)
    response = client.get(f'/api/workspace/file?path=sharedfile.txt&conversation_id={convo_id}')
    assert response.status_code == 200
    assert response.get_json()['content'] == 'shared content'
