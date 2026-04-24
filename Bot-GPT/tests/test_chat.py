import pytest
import json
import threading
from unittest.mock import MagicMock, call
from app import socketio
import chat
import os
from flask_login import login_user
from models import User, save_conversation, add_to_conversation_index, add_user_to_conversation_index
from repo_index import save_repo_index
from memory_store import upsert_fact


def mock_chat_stream_sequence(*responses):
    """Helper to create a valid sequence of responses for mocked call_stream, prepending the classifier response."""
    sequence = [iter(["{\"mode\": \"standard\", \"confidence\": 0.9}"])]
    for response in responses:
        sequence.append(iter([response]))
    return sequence

def test_chat_message_handling(socketio_test_client, test_user, mocker):
    """Test sending a message and receiving a simple AI response."""
    # Mock the AI response stream
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = mock_chat_stream_sequence("Hello, this is the AI.")
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
    mock_stream.side_effect = mock_chat_stream_sequence(tool_call_response, final_answer)
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

def test_write_file_emits_open_canvas(socketio_test_client, test_user, mocker, app):
    """Test that a write_file tool call emits an open_canvas event."""
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_handle_tool = mocker.patch("chat.handle_tool_call")
    mocker.patch("chat.update_conversation_title")

    # Mock initialize_chat to bypass conversation lookups
    mock_init = mocker.patch("chat.initialize_chat")
    mock_init.return_value = ("test-model", "sys-prompt", {"id": "test_convo_123", "owner_id": 1, "messages": []}, "path/to/convo.json")

    tool_call_response = '```json\n{"tool": "write_file", "parameters": {"path": "test.txt", "content": "hello"}}\n```'
    final_answer = "I have written the file."
    mock_stream.side_effect = mock_chat_stream_sequence(tool_call_response, final_answer)
    mock_handle_tool.return_value = ({"status": "file_written", "path": "test.txt"}, True)

    convo_id = "test_convo_123"
    socketio_test_client.emit('join', {'room': convo_id})

    with app.app_context():
        socketio_test_client.emit('chat_message', {
            'messages': json.dumps([{'role': 'user', 'content': 'write a file'}]),
            'model': 'test-model',
            'conversation_id': convo_id
        })

    received = socketio_test_client.get_received()
    ai_responses = [args['args'][0] for args in received if args['name'] == 'ai_response']

    # Check for the open_canvas event
    open_canvas_events = [r for r in ai_responses if r.get('type') == 'open_canvas']
    assert len(open_canvas_events) == 1
    assert open_canvas_events[0]['filename'] == 'test.txt'


def test_tool_call_parser_handles_mixed_prose_and_nested_json(socketio_test_client, test_user, mocker, app):
    """Tool call extraction should work even with prose and nested braces."""
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_handle_tool = mocker.patch("chat.handle_tool_call")
    mocker.patch("chat.update_conversation_title")

    tool_call_response = (
        "I will gather context first.\n\n"
        "```json\n"
        "{\"tool\":\"write_file\",\"parameters\":{\"path\":\"notes.txt\",\"content\":\"{\\\"nested\\\":{\\\"ok\\\":true}}\"}}\n"
        "```\n"
        "Then I will summarize."
    )
    mock_stream.side_effect = mock_chat_stream_sequence(tool_call_response, "Done.")
    mock_handle_tool.return_value = ({"status": "file_written", "path": "notes.txt"}, True)

    with app.app_context():
        socketio_test_client.emit('chat_message', {
            'messages': json.dumps([{'role': 'user', 'content': 'write notes'}]),
            'model': 'test-model',
            'conversation_id': ''
        })

    received = socketio_test_client.get_received()
    tool_call_events = [
        args['args'][0] for args in received
        if args['name'] == 'ai_response' and args['args'][0].get('type') == 'tool_call'
    ]

    assert len(tool_call_events) == 1
    assert tool_call_events[0]['name'] == 'write_file'
    assert tool_call_events[0]['params']['path'] == 'notes.txt'


def test_load_conversation_includes_active_run(socketio_test_client, test_user, app):
    """Test that reloading a conversation includes active run state for the UI."""
    convo_id = "active_run_convo"

    with app.app_context():
        convo_path = os.path.join(app.instance_path, str(test_user.id), 'conversations', f'{convo_id}.json')
        save_conversation(convo_path, {
            'id': convo_id,
            'owner_id': test_user.id,
            'title': 'Running Chat',
            'participants': [{'user_id': test_user.id, 'role': 'owner'}],
            'messages': [{'role': 'user', 'content': 'keep going'}],
            'artifacts': [{
                'artifact_id': 'utils.py',
                'conversation_id': convo_id,
                'artifact_type': 'code',
                'last_updated_at': 1710000000,
                'title': 'utils.py',
            }],
            'artifact_versions': {'utils.py': []},
            'last_active_artifact_id': 'utils.py',
        })
        index_path = os.path.join(app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, convo_id, test_user.id)
        user_index_path = os.path.join(app.instance_path, 'user_conversation_index.json')
        add_user_to_conversation_index(user_index_path, test_user.id, convo_id)

    chat.AGENT_SESSIONS[convo_id] = {
        'running': True,
        'agent_mode': False,
        'partial_response': 'Still working',
        'stage': 'answering',
        'tool_name': None,
        'tool_params': None,
        'error': None,
    }

    socketio_test_client.emit('load_conversation', {'conversation_id': convo_id})
    received = socketio_test_client.get_received()
    payloads = [event['args'][0] for event in received if event['name'] == 'conversation_loaded']

    assert len(payloads) == 1
    assert payloads[0]['active_run']['is_running'] is True
    assert payloads[0]['active_run']['partial_response'] == 'Still working'
    assert payloads[0]['last_active_artifact_id'] == 'utils.py'
    assert payloads[0]['artifacts'][0]['artifact_id'] == 'utils.py'

    chat.AGENT_SESSIONS.pop(convo_id, None)


def test_handle_ai_response_archives_memory(app, test_user, mocker):
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = mock_chat_stream_sequence("Cross-session memory should persist.")
    mocker.patch("chat.update_conversation_title")
    memory_cls = mocker.patch("memory.MemoryManager")

    with app.test_request_context("/"):
        login_user(test_user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "Please remember I prefer concise answers."}]),
            "model": "test-model",
            "conversation_id": "",
        }))

    done_events = [event for event in events if event.get("type") == "done"]
    assert len(done_events) == 1
    memory_cls.return_value.archive_conversation.assert_called_once()


def test_repo_question_without_tool_call_uses_deterministic_fallback(app, test_user, mocker):
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = mock_chat_stream_sequence("I will think about it.")
    mocker.patch("chat.update_conversation_title")

    with app.app_context():
        save_repo_index(
            test_user.id,
            {
                "repos": [
                    {"name": "alpha", "path": "/tmp/alpha", "last_commit_time": 200, "last_modified_time": 180, "file_count": 10},
                    {"name": "beta", "path": "/tmp/beta", "last_commit_time": 100, "last_modified_time": 220, "file_count": 5},
                ],
                "selected_repo_path": None,
                "updated_at": None,
            },
        )

    with app.test_request_context("/"):
        login_user(test_user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "Which one of my repos is the most active?"}]),
            "model": "test-model",
            "conversation_id": "",
        }))

    final_answers = [event for event in events if event.get("type") == "final_answer"]
    done_events = [event for event in events if event.get("type") == "done"]
    assert done_events
    assert final_answers
    assert "Most active repo appears to be" in final_answers[-1]["content"]


def test_repo_question_with_no_configured_paths_returns_clean_block_message(app, test_user, mocker):
    app.config["REPO_SCAN_BASE_PATHS"] = "[]"
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = mock_chat_stream_sequence("Thinking...")
    mocker.patch("chat.update_conversation_title")

    with app.app_context():
        save_repo_index(test_user.id, {"repos": [], "selected_repo_path": None, "updated_at": None})

    with app.test_request_context("/"):
        login_user(test_user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "Analyze my repos"}]),
            "model": "test-model",
            "conversation_id": "",
        }))

    final_answers = [event for event in events if event.get("type") == "final_answer"]
    assert final_answers
    assert "configured repo folder" in final_answers[-1]["content"]
    assert any(event.get("type") == "done" for event in events)


def test_repo_discovery_timeout_unblocks_ui(app, test_user, mocker):
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = mock_chat_stream_sequence("No tool calls from model")
    mocker.patch("chat.update_conversation_title")
    mocker.patch("chat_ai.discover_local_repositories", return_value={"status": "error", "error": "Repository discovery timed out before completion.", "repos": []})
    with app.app_context():
        save_repo_index(test_user.id, {"repos": [], "selected_repo_path": None, "updated_at": None})

    with app.test_request_context("/"):
        login_user(test_user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "most recently updated repo?"}]),
            "model": "test-model",
            "conversation_id": "",
        }))

    assert any(event.get("type") == "activity_update" and event.get("stage") == "error" for event in events)
    assert any(event.get("type") == "done" for event in events)


def test_empty_model_response_finalizes_cleanly(app, test_user, mocker):
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = mock_chat_stream_sequence("   ", "   ")
    mocker.patch("chat.update_conversation_title")

    with app.test_request_context("/"):
        login_user(test_user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "Which one of my repos is the most active?"}]),
            "model": "test-model",
            "conversation_id": "",
        }))

    final_answers = [event for event in events if event.get("type") == "final_answer"]
    assert final_answers
    assert (
        "usable model response" in final_answers[-1]["content"]
        or "Most active repo appears" in final_answers[-1]["content"]
        or "configured repo folder" in final_answers[-1]["content"]
    )
    assert any(event.get("type") == "done" for event in events)


def test_terminal_done_event_emitted_on_model_failure(app, test_user, mocker):
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = [iter(["{\"mode\": \"standard\", \"confidence\": 0.9}"]), RuntimeError("model backend unavailable")]
    mocker.patch("chat.update_conversation_title")

    with app.test_request_context("/"):
        login_user(test_user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "hello"}]),
            "model": "test-model",
            "conversation_id": "",
        }))

    assert any(event.get("type") == "agent_error" for event in events)
    assert any(event.get("type") == "done" for event in events)


def test_os_capability_refusal_is_overridden_with_policy_message(app, test_user, mocker):
    app.config["OS_AGENT_ENABLED"] = False
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_stream.side_effect = mock_chat_stream_sequence("I cannot access your desktop or your system.")
    mocker.patch("chat.update_conversation_title")

    with app.test_request_context("/"):
        login_user(test_user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "Take a screenshot of my desktop"}]),
            "model": "test-model",
            "conversation_id": "",
            "os_control_enabled": True,
        }))

    final_answers = [event for event in events if event.get("type") == "final_answer"]
    assert final_answers
    assert "OS control is currently disabled" in final_answers[-1]["content"]
    assert "cannot access your desktop" not in final_answers[-1]["content"].lower()


def test_call_stream_prompt_contains_user_memory_and_excludes_recalled_memory_dump(app, mocker):
    captured_prompt = {"value": ""}

    def fake_stream(_model, _messages, system_prompt):
        if "=== USER MEMORY ===" in system_prompt:
            captured_prompt["value"] = system_prompt
        if "strict response-depth router" in system_prompt.lower():
            return iter(['{"mode":"standard","confidence":0.95}'])
        return iter(["Acknowledged."])

    mocker.patch("chat.call_ollama_chat_stream", side_effect=fake_stream)
    mocker.patch("chat.update_conversation_title")

    with app.app_context():
        upsert_fact(
            77,
            scope="user",
            key="identity:display_name",
            value="Jason",
            source_conversation_id="seed",
            source_message_index=0,
            confidence=0.95,
        )

    with app.test_request_context("/"):
        user = User(id=77, username="jasonk87", password_hash=None)
        login_user(user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "Please summarize the current workstream."}]),
            "model": "test-model",
            "conversation_id": "",
            "response_mode_preference": "standard",
        }))

    assert any(event.get("type") == "done" for event in events)
    assert "=== USER MEMORY ===" in captured_prompt["value"]
    assert "username: jasonk87" in captured_prompt["value"]
    assert "display_name: Jason" in captured_prompt["value"]
    assert "This is trusted user identity memory. Use it when relevant." in captured_prompt["value"]
    assert "=== RECALLED MEMORY ===" not in captured_prompt["value"]
    assert "I am a language model" not in captured_prompt["value"]
    assert "I do not retain memory" not in captured_prompt["value"]


def test_identity_question_uses_model_path_with_user_memory_prompt(app, mocker):
    prompts_seen = []

    def fake_stream(_model, _messages, system_prompt):
        prompts_seen.append(system_prompt)
        if "strict response-depth router" in system_prompt.lower():
            return iter(['{"mode":"standard","confidence":0.95}'])
        return iter(["Yes — your username is jasonk87 and your display name is Jason."])

    mock_stream = mocker.patch("chat.call_ollama_chat_stream", side_effect=fake_stream)
    mocker.patch("chat.update_conversation_title")

    with app.app_context():
        upsert_fact(
            78,
            scope="user",
            key="identity:display_name",
            value="Jason",
            source_conversation_id="seed",
            source_message_index=0,
            confidence=0.95,
        )

    with app.test_request_context("/"):
        user = User(id=78, username="jasonk87", password_hash=None)
        login_user(user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "What is my name?"}]),
            "model": "test-model",
            "conversation_id": "",
            "response_mode_preference": "standard",
        }))

    final_answers = [event for event in events if event.get("type") == "final_answer"]
    assert final_answers
    assert "jasonk87" in final_answers[-1]["content"]
    assert "Jason" in final_answers[-1]["content"]
    assert "do not have memory" not in final_answers[-1]["content"].lower()
    assert mock_stream.call_count >= 1
    assert any("=== USER MEMORY ===" in prompt and "username: jasonk87" in prompt for prompt in prompts_seen)


def test_identity_prompt_uses_current_user_memory_without_cross_user_leakage(app, mocker):
    prompts_seen = []

    def fake_stream(_model, _messages, system_prompt):
        prompts_seen.append(system_prompt)
        if "strict response-depth router" in system_prompt.lower():
            return iter(['{"mode":"standard","confidence":0.95}'])
        return iter(["I know your username from USER MEMORY."])

    mocker.patch("chat.call_ollama_chat_stream", side_effect=fake_stream)
    mocker.patch("chat.update_conversation_title")

    with app.app_context():
        upsert_fact(
            79,
            scope="user",
            key="identity:display_name",
            value="Alice",
            source_conversation_id="seed",
            source_message_index=0,
            confidence=0.95,
        )

    with app.test_request_context("/"):
        user = User(id=79, username="alice99", password_hash=None)
        login_user(user)
        events = list(chat.handle_ai_response({
            "messages": json.dumps([{"role": "user", "content": "Do you know my name?"}]),
            "model": "test-model",
            "conversation_id": "",
            "response_mode_preference": "standard",
        }))

    assert any(event.get("type") == "done" for event in events)
    joined_prompts = "\n".join(prompts_seen)
    assert "username: alice99" in joined_prompts
    assert "display_name: Alice" in joined_prompts
    assert "username: jasonk87" not in joined_prompts
    assert "display_name: Jason" not in joined_prompts
