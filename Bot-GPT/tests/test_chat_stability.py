import pytest
from unittest.mock import patch, MagicMock
import json
from requests.exceptions import ConnectionError

def test_chat_handles_ollama_timeout(socketio_test_client):
    """
    Tests that the chat handler gracefully terminates when the Ollama request times out.
    """
    # Mock for the title generation call, which also uses requests.post
    mock_title_response = MagicMock()
    mock_title_response.json.return_value = {"message": {"content": "Test Title"}}
    mock_title_response.raise_for_status.return_value = None

    # Patch the functions where they are looked up: in the 'chat' module.
    with patch('chat.call_ollama_chat_stream', side_effect=ConnectionError("AI service timed out")), \
         patch('chat.requests.post', return_value=mock_title_response):
        socketio_test_client.connect()

        # Define the message payload without a conversation_id to start a new chat
        chat_message_data = {
            'messages': json.dumps([{'role': 'user', 'content': 'Hello'}]),
            'model': 'test-model',
        }

        # Emit the chat message
        socketio_test_client.emit('chat_message', chat_message_data)

        # The test client's get_received should now get the events
        received = socketio_test_client.get_received()

        # We expect several events, including conversation_id, agent_error, and done.
        assert len(received) >= 2, f"Expected at least 2 events, but got {received}"

        event_names = [event['name'] for event in received]
        assert 'ai_response' in event_names, "Expected 'ai_response' event"

        ai_responses = [event['args'][0] for event in received if event['name'] == 'ai_response']

        error_event = next((arg for arg in ai_responses if arg.get('type') == 'agent_error'), None)
        assert error_event is not None, "Expected an agent_error event"
        assert "AI service timed out" in error_event.get('error', '')

        done_event = next((arg for arg in ai_responses if arg.get('type') == 'done'), None)
        assert done_event is not None, "A 'done' event was not received"

        socketio_test_client.disconnect()
