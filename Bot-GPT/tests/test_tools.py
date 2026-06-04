
from unittest.mock import MagicMock
from tools.file_system import write_file
from tools.web_search import _web_context_limit_for_model, web_search

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


def test_web_search_handles_missing_google_client_dependency(app, mocker):
    mocker.patch("tools.web_search.build", None)
    with app.app_context():
        app.config["GOOGLE_API_KEY"] = "fake-key"
        app.config["GOOGLE_CSE_ID"] = "fake-cse"
        result = web_search("latest ai news")
    assert "Missing required libraries" in result
    assert "Recovery:" in result


def test_web_search_uses_large_context_for_gemini_25():
    assert _web_context_limit_for_model("gemini-2.5-flash-lite (Max Thinking)") == 700_000
    assert _web_context_limit_for_model("gemini-1.5-flash") == 300_000
    assert _web_context_limit_for_model("llama3") == 80_000
