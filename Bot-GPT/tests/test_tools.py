
import pytest
from unittest.mock import MagicMock
from tools.file_system import write_file

def test_write_file_emits_refresh_and_open(app, test_user, mocker):
    """Test that write_file emits refresh_files and returns correct status."""
    mock_socketio = MagicMock()
    mocker.patch('tools.file_system.socketio', mock_socketio)

    with app.app_context():
        result = write_file(
            path='test.txt',
            content='hello',
            conversation_id='test_convo',
            user_id=test_user.id
        )

    assert result['status'] == 'file_written'
    mock_socketio.emit.assert_called_once_with(
        'refresh_files',
        {'conversation_id': 'test_convo'},
        room='test_convo'
    )
