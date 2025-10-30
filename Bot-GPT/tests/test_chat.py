import pytest
import json
import threading
from unittest.mock import MagicMock, call
from extensions import socketio
import chat

def test_chat_message_handling(socketio_test_client, test_user, mocker):
    """Test sending a message and receiving a simple AI response."""
    # Mock the AI response stream
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.return_value = iter(["Hello, this is the AI."])
    mocker.patch("chat.update_conversation_title")

    socketio_test_client.emit('chat_message', {
        'messages': json.dumps([{'role': 'user', 'content': 'hello'}]),
        'model': 'test-model',
        'conversation_id': ''
    })

    received = socketio_test_client.get_received()
    # A simplified check to ensure the main events are received
    event_types = [event['name'] for event in received]
    assert 'ai_response' in event_types

    # Check for specific event subtypes
    ai_response_args = [event['args'][0] for event in received if event['name'] == 'ai_response']
    response_types = {arg.get('type') for arg in ai_response_args}
    assert 'conversation_id' in response_types
    assert 'assistant_chunk' in response_types
    assert 'done' in response_types

def test_tool_call_in_chat(socketio_test_client, test_user, mocker, app):
    """Test a chat that involves a tool call."""
    # Mock the AI and the tool
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_handle_tool = mocker.patch("chat.handle_tool_call")
    mocker.patch("chat.update_conversation_title")

    tool_call_response = '```json\n{"tool": "list_files", "parameters": {}}\n```'
    final_answer = "Files listed."
    mock_stream.side_effect = [iter([tool_call_response]), iter([final_answer])]
    mock_handle_tool.return_value = ("file1.txt", False)

    with app.app_context():
        socketio_test_client.emit('chat_message', {
            'messages': json.dumps([{'role': 'user', 'content': 'list files'}]),
            'model': 'test-model',
            'conversation_id': ''
        })

    received = socketio_test_client.get_received()
    # Check that a tool call event was emitted
    tool_call_events = [
        args['args'][0] for args in received
        if args['name'] == 'ai_response' and args['args'][0].get('type') == 'tool_call'
    ]
    assert len(tool_call_events) == 1
    assert tool_call_events[0]['name'] == 'list_files'

def test_write_file_emits_refresh_and_open(socketio_test_client, test_user, mocker, app):
    """Test that a write_file tool call emits refresh_files and open_canvas."""
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_handle_tool = mocker.patch("chat.handle_tool_call")
    mocker.patch("chat.update_conversation_title")

    tool_call_response = '```json\n{"tool": "write_file", "parameters": {"path": "test.txt", "content": "hello"}}\n```'
    mock_stream.return_value = iter([tool_call_response])
    mock_handle_tool.return_value = ({"status": "file_written", "path": "test.txt"}, True)

    with app.app_context():
        socketio_test_client.emit('chat_message', {
            'messages': json.dumps([{'role': 'user', 'content': 'write a file'}]),
            'model': 'test-model',
            'conversation_id': ''
        })

    received = socketio_test_client.get_received()
    ai_responses = [args['args'][0] for args in received if args['name'] == 'ai_response']

    # Check for the open_canvas event
    open_canvas_events = [r for r in ai_responses if r.get('type') == 'open_canvas']
    assert len(open_canvas_events) == 1
    assert open_canvas_events[0]['filename'] == 'test.txt'

    # Check for the refresh_files event
    refresh_files_events = [r for r in ai_responses if r.get('type') == 'refresh_files']
    assert len(refresh_files_events) == 1
