import json
import threading
from unittest.mock import MagicMock, patch
import requests
import pytest
from flask_login import login_user
from models import User
from chat import chat_proxy, AGENT_SESSIONS, handle_ai_response
from tools import set_plan, update_task_status

@pytest.fixture
def socketio_test_client(app, test_user):
    from extensions import socketio
    with app.test_request_context('/'):
        login_user(test_user)
        client = socketio.test_client(app)
        yield client
        client.disconnect()

def test_full_chat_with_tool_call(app, test_user, mocker):
    """
    Tests a full chat conversation with a tool call, including streaming chunks.
    """
    # 1. Mock the `call_ollama_chat_stream` and `update_conversation_title` functions.
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mocker.patch("chat.update_conversation_title", new=lambda convo, messages: setattr(convo, 'title', 'List Files'))

    # Canned responses from the mocked Ollama API.
    tool_call_response = """<think>I need to list the files in the workspace.</think>```json
{
    "tool": "list_files",
    "parameters": {}
}
```"""
    final_answer_response = "I have listed the files for you."

    # Set up the mock to return the responses in order.
    mock_stream.side_effect = [
        iter([tool_call_response]),
        iter([final_answer_response]),
    ]

    # 2. Call the chat_proxy function directly within a request context.
    with app.test_request_context('/api/chat?messages=[{"role":"user","content":"list the files"}]&model=test-model'):
        # Manually log in the test user.
        login_user(test_user)

        from chat import chat_proxy
        response = chat_proxy()

        # 3. Assert the response stream contains the expected events.
        assert response.status_code == 200

        events = [json.loads(line.replace("data: ", "")) for line in response.response if line]

        # Find the index of the tool_call event
        tool_call_index = -1
        for i, event in enumerate(events):
            if event["type"] == "tool_call":
                tool_call_index = i
                break

        assert tool_call_index != -1, "tool_call event not found"

        # Assert events before the tool_call
        assert events[0]["type"] == "conversation_id"
        assert events[1]["type"] == "assistant_chunk"
        assert events[2]["type"] == "assistant_end"

        # Assert the tool_call itself
        assert events[tool_call_index]["type"] == "tool_call"

        # Assert events after the tool_call, which now include chunks
        assert events[tool_call_index + 1]["type"] == "tool_result_chunk"
        assert events[tool_call_index + 2]["type"] == "tool_result"
        assert events[tool_call_index + 3]["type"] == "assistant_chunk"
        assert events[tool_call_index + 4]["type"] == "assistant_end"
        assert events[tool_call_index + 5]["type"] == "final_answer"
        assert events[tool_call_index + 6]["type"] == "done"
        assert events[tool_call_index + 6]["title"] == "List Files"


def test_agent_mode_with_stop(app, test_user, socketio_test_client, mocker):
    """
    Tests that the stop_agent event correctly updates the agent's state.
    """
    from chat import AGENT_SESSIONS
    from extensions import socketio
    convo_id = "stop_test_convo"
    agent_stop_processed = threading.Event()

    def mock_handle_ai_response(*args, **kwargs):
        AGENT_SESSIONS[convo_id] = {"stop_requested": False}
        while not AGENT_SESSIONS.get(convo_id, {}).get("stop_requested"):
            socketio.sleep(0.01)

        if convo_id in AGENT_SESSIONS:
            del AGENT_SESSIONS[convo_id]
        agent_stop_processed.set()
        yield {"type": "done"}

    mocker.patch("chat.handle_ai_response", side_effect=mock_handle_ai_response)

    client = socketio_test_client

    def run_chat():
        with app.test_request_context('/'):
            login_user(test_user)
            client.emit("chat_message", {
                "messages": json.dumps([{"role": "user", "content": "do a long task"}]),
                "model": "test-model", "agent_mode": True, "conversation_id": convo_id
            })

    socketio.start_background_task(run_chat)
    socketio.sleep(0.1)

    assert convo_id in AGENT_SESSIONS, "Agent session was not created."
    client.emit("stop_agent", {"conversation_id": convo_id})

    assert agent_stop_processed.wait(timeout=5), "Agent did not process the stop signal."
    assert convo_id not in AGENT_SESSIONS, "Agent session was not cleaned up."


def test_plan_visualization_events(app, socketio_test_client, test_user):
    """
    Tests that the plan visualization tools emit the correct Socket.IO events.
    """
    from tools import set_plan
    from extensions import socketio
    convo_id = "plan_test_convo"

    client = socketio_test_client
    client.emit('join', {'room': convo_id})

    plan_steps = ["Step 1", "Step 2"]
    # This needs to be called within a request context to access current_app
    with app.test_request_context('/'):
        set_plan(steps=plan_steps, conversation_id=convo_id)

    # Poll for the event with a timeout
    import time
    start_time = time.time()
    received = []
    while time.time() - start_time < 5:
        received = client.get_received()
        if any(e['name'] == 'plan_updated' for e in received):
            break
        socketio.sleep(0.1)

    assert any(e['name'] == 'plan_updated' for e in received), "Did not receive 'plan_updated' event."

    plan_update_event = next(e for e in received if e['name'] == 'plan_updated')
    assert plan_update_event['args'][0]['steps'] == plan_steps
