import json
from models import Conversation, ConversationParticipant


def test_home_page(client):
    """Test that the home page loads and contains expected content."""
    response = client.get('/')
    assert response.status_code == 200
    # Check for a crucial part of the page, like the main script.
    assert b'/static/js/main.js' in response.data


def test_get_workspace_files_route(logged_in_client, db, test_user, mocker):
    """
    Tests the workspace files API endpoint for an authenticated user.
    """
    # 1. Setup: Create a conversation owned by the test user.
    convo = Conversation(
        id="test_convo_123", title="Test Convo", owner_id=test_user.id
    )
    participant = ConversationParticipant(
        user_id=test_user.id, conversation_id=convo.id, role='owner'
    )
    db.session.add(convo)
    db.session.add(participant)
    db.session.commit()

    # 2. Mock filesystem interactions to isolate the test.
    mocker.patch('routes.get_workspace_path', return_value='/fake/path')
    mock_get_file_tree = mocker.patch('routes.get_file_tree', return_value=[
        {'name': 'test.txt', 'type': 'file', 'path': 'test.txt'}
    ])

    # 3. Make the request.
    response = logged_in_client.get('/api/workspace/files/test_convo_123')

    # 4. Assert the response is correct.
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data == [{'name': 'test.txt', 'type': 'file', 'path': 'test.txt'}]
    mock_get_file_tree.assert_called_once_with('/fake/path')


def test_get_workspace_files_unauthorized(client):
    """
    Tests that a non-logged-in user is redirected from a protected API.
    """
    # Flask-Login's default behavior for @login_required is to redirect to
    # the login_view, which results in a 302 status code for a browser.
    response = client.get('/api/workspace/files/some_convo_id')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']
