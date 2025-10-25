import json
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
    # 1. Mock the `get_workspace_path`, `secure_filename`, `os.path.join` and `file.save` functions.
    mocker.patch('workspace.get_workspace_path', return_value='/fake/path')
    mocker.patch('werkzeug.utils.secure_filename', return_value='test.txt')
    mocker.patch('os.path.join')
    mocker.patch('werkzeug.datastructures.FileStorage.save')


    # 2. Make the request.
    class MockFile:
        filename = 'test.txt'

        def save(self, path):
            pass

    mock_request = mocker.patch('workspace.request')
    mock_request.files.getlist.return_value = [MockFile()]
    mock_request.form.get.side_effect = ['Here is a file.', 'test_convo_id']

    response = logged_in_client.post('/api/upload')

    # 3. Assert the response is correct.
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'User uploaded the following files' in data['message']
    assert 'test.txt' in data['message']
    assert data['conversation_id'] == 'test_convo_id'
