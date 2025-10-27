import json
import io
from unittest.mock import MagicMock
from models import User
from extensions import db


def test_get_users(logged_in_client, app, test_user):
    """
    Tests that the get_users API endpoint returns a list of all users
    except the current user.
    """
    # 1. Setup: Create another user.
    other_user = User(username="otheruser")
    other_user.set_password("password")
    db.session.add(other_user)
    db.session.commit()

    # 2. Make the request.
    response = logged_in_client.get("/api/users")

    # 3. Assert the response is correct.
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 1
    assert data[0]["username"] == "otheruser"


def test_upload_file(logged_in_client, mocker):
    """
    Tests the file upload API endpoint.
    """
    # 1. Mock file system operations to avoid creating directories and files.
    mocker.patch("os.path.join", return_value="/tmp/fake_workspace/test.txt")
    mocker.patch("builtins.open", mocker.mock_open())
    mocker.patch("werkzeug.utils.secure_filename", return_value="test.txt")
    mocker.patch("os.makedirs")
    # Need to mock the save method on the file object
    mock_file_storage = MagicMock()
    mock_file_storage.filename = "test.txt"
    mock_file_storage.save.return_value = None
    mocker.patch(
        "werkzeug.datastructures.FileStorage.save", mock_file_storage.save
    )

    # 2. Prepare the request data. Note: No conversation_id is sent for a new chat.
    data = {
        "files[]": (io.BytesIO(b"file content"), "test.txt"),
        "prompt": "Here is a file.",
    }

    # 3. Make the request.
    response = logged_in_client.post(
        "/api/upload", data=data, content_type="multipart/form-data"
    )

    # 4. Assert the response is correct.
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "User uploaded the following files" in data["message"]
    assert "test.txt" in data["message"]
