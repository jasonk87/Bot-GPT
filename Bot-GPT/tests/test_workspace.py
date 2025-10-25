import json
import io
from models import User

def test_get_users(logged_in_client, db, test_user):
    """
    Tests that the get_users API endpoint returns a list of all users
    except the current user.
    """
    # 1. Setup: Create another user.
    other_user = User(username='otheruser')
    other_user.set_password('password')
    db.session.add(other_user)
    db.session.commit()

    # 2. Make the request.
    response = logged_in_client.get('/api/users')

    # 3. Assert the response is correct.
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 1
    assert data[0]['username'] == 'otheruser'

def test_upload_file(logged_in_client, mocker):
    """
    Tests the file upload API endpoint.
    """
    # 1. Mock the `get_workspace_path` function to avoid creating directories.
    mocker.patch('workspace.get_workspace_path', return_value='/tmp/fake_workspace')
    mocker.patch('os.path.join', return_value='/tmp/fake_workspace/test.txt')
    mocker.patch('builtins.open', mocker.mock_open())


    # 2. Prepare the request data.
    data = {
        'files[]': (io.BytesIO(b"file content"), 'test.txt'),
        'prompt': 'Here is a file.',
        'conversation_id': 'test_convo_id'
    }

    # 3. Make the request.
    response = logged_in_client.post(
        '/api/upload', data=data, content_type='multipart/form-data'
    )

    # 4. Assert the response is correct.
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'User uploaded the following files' in data['message']
    assert 'test.txt' in data['message']
    assert data['conversation_id'] == 'test_convo_id'
