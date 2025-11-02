
import uuid
import os
from io import BytesIO
from models import save_conversation, add_to_conversation_index, get_all_conversations_for_user, add_user_to_conversation_index

def login(client, username, password):
    """Helper function to log in a user."""
    return client.post('/login', json={'username': username, 'password': password}, follow_redirects=True)

def test_get_users_api(client, two_users):
    """Test the API endpoint for getting users."""
    user1, user2 = two_users
    login(client, user1.username, 'password')
    response = client.get('/api/users')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]['username'] == user2.username

def test_upload_file_new_conversation(client, test_user, app):
    """Test uploading a file to a new conversation."""
    login(client, test_user.username, 'password')

    data = {
        'files[]': (BytesIO(b'my file contents'), 'test.txt'),
        'prompt': 'Analyze this file.'
    }

    response = client.post('/api/upload', data=data, content_type='multipart/form-data')
    assert response.status_code == 200
    json_data = response.get_json()
    assert 'conversation_id' in json_data
    assert 'message' in json_data

def test_share_conversation_api(client, two_users, app):
    """Test sharing a conversation with another user."""
    user1, user2 = two_users
    convo_id = str(uuid.uuid4())

    with app.app_context():
        convo_data = {
            "id": convo_id, "owner_id": user1.id, "title": "Shared Convo",
            "participants": [{"user_id": user1.id, "role": "owner"}], "messages": []
        }
        convo_path = os.path.join(app.instance_path, str(user1.id), 'conversations', f'{convo_id}.json')
        save_conversation(convo_path, convo_data)
        index_path = os.path.join(app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, convo_id, user1.id)
        user_convo_index_path = os.path.join(app.instance_path, 'user_conversation_index.json')
        add_user_to_conversation_index(user_convo_index_path, user1.id, convo_id)


    login(client, user1.username, 'password')
    response = client.post(f'/api/conversation/{convo_id}/share', json={'user_id': user2.id})
    assert response.status_code == 201
    assert response.get_json()['message'] == 'Conversation shared successfully'

def test_summarize_conversation_api(client, two_users, app, mocker):
    """Test the conversation summarization API endpoint."""
    user1, user2 = two_users
    convo_id = str(uuid.uuid4())

    with app.app_context():
        convo_data = {
            "id": convo_id, "owner_id": user1.id, "title": "Summary Test",
            "participants": [{"user_id": user1.id, "role": "owner"}],
            "messages": [
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "The capital of France is Paris."}
            ]
        }
        convo_path = os.path.join(app.instance_path, str(user1.id), 'conversations', f'{convo_id}.json')
        save_conversation(convo_path, convo_data)
        index_path = os.path.join(app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, convo_id, user1.id)
        user_convo_index_path = os.path.join(app.instance_path, 'user_conversation_index.json')
        add_user_to_conversation_index(user_convo_index_path, user1.id, convo_id)

    mock_stream = mocker.patch("workspace.call_ollama_chat_stream")
    mock_stream.return_value = iter(["This is a summary."])

    login(client, user1.username, 'password')
    response = client.get(f'/api/conversation/{convo_id}/summarize')
    assert response.status_code == 200
    assert response.data.decode('utf-8') == 'This is a summary.'

def test_get_all_conversations_for_user(client, two_users, app):
    """Test the optimized get_all_conversations_for_user function."""
    user1, user2 = two_users
    convo_id = str(uuid.uuid4())

    with app.app_context():
        # Clean up index files before test
        index_path = os.path.join(app.instance_path, 'conversation_index.json')
        user_convo_index_path = os.path.join(app.instance_path, 'user_conversation_index.json')
        if os.path.exists(index_path):
            os.remove(index_path)
        if os.path.exists(user_convo_index_path):
            os.remove(user_convo_index_path)

        convo_data = {
            "id": convo_id, "owner_id": user1.id, "title": "Test Convo",
            "participants": [{"user_id": user1.id, "role": "owner"}], "messages": []
        }
        convo_path = os.path.join(app.instance_path, str(user1.id), 'conversations', f'{convo_id}.json')
        save_conversation(convo_path, convo_data)
        add_to_conversation_index(index_path, convo_id, user1.id)
        add_user_to_conversation_index(user_convo_index_path, user1.id, convo_id)

    # Share the conversation with user2
    login(client, user1.username, 'password')
    client.post(f'/api/conversation/{convo_id}/share', json={'user_id': user2.id})

    with app.app_context():
        # Test for user1
        user1_convos = get_all_conversations_for_user(app.instance_path, user1.id)
        assert len(user1_convos) == 1
        assert user1_convos[0]['id'] == convo_id
        assert user1_convos[0]['role'] == 'owner'

        # Test for user2
        user2_convos = get_all_conversations_for_user(app.instance_path, user2.id)
        assert len(user2_convos) == 1
        assert user2_convos[0]['id'] == convo_id
        assert user2_convos[0]['role'] == 'participant'
