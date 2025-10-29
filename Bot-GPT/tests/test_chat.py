import json
import threading
from flask_login import login_user


def test_full_chat_with_tool_call(app, test_user, mocker):
    """
    Tests a full chat conversation with a tool call.
    """
    # 1. Mock the `call_ollama_chat_stream` and `update_conversation_title` functions.
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mocker.patch(
        "chat.update_conversation_title",
        new=lambda convo, messages: setattr(convo, "title", "List Files"),
    )

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
    with app.test_request_context(
        '/api/chat?messages=[{"role":"user","content":"list the files"}]&model=test-model'
    ):
        # Manually log in the test user.
        login_user(test_user)

        from chat import chat_proxy

        response = chat_proxy()

        # 3. Assert the response stream contains the expected events.
        assert response.status_code == 200

        events = [
            json.loads(line.replace("data: ", "")) for line in response.response if line
        ]

        assert events[0]["type"] == "conversation_id"
        assert events[1]["type"] == "assistant_chunk"
        assert events[2]["type"] == "assistant_end"
        assert events[3]["type"] == "tool_call"
        assert events[4]["type"] == "tool_result"
        assert events[5]["type"] == "assistant_chunk"
        assert events[6]["type"] == "assistant_end"
        assert events[7]["type"] == "final_answer"
        assert events[8]["type"] == "done"
        assert events[8]["title"] == "List Files"


def test_agent_mode_with_stop(app, test_user, socketio, mocker):
    """
    Tests that the stop_agent event correctly updates the agent's state.
    """
    from chat import AGENT_SESSIONS

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

    with app.test_request_context("/"):
        login_user(test_user)
        client = socketio.test_client(app)
        assert client.is_connected()

        def run_chat():
            with app.test_request_context("/"):
                login_user(test_user)
                client.emit(
                    "chat_message",
                    {
                        "messages": json.dumps(
                            [{"role": "user", "content": "do a long task"}]
                        ),
                        "model": "test-model",
                        "agent_mode": True,
                        "conversation_id": convo_id,
                    },
                )

        socketio.start_background_task(run_chat)
        socketio.sleep(0.1)

        assert convo_id in AGENT_SESSIONS, "Agent session was not created."
        client.emit("stop_agent", {"conversation_id": convo_id})

        assert agent_stop_processed.wait(
            timeout=5
        ), "Agent did not process the stop signal."
        assert convo_id not in AGENT_SESSIONS, "Agent session was not cleaned up."

        client.disconnect()


def test_plan_visualization_events(app, socketio, test_user):
    """
    Tests that the plan visualization tools emit the correct Socket.IO events.
    """
    from tools import set_plan

    convo_id = "plan_test_convo"

    with app.test_request_context("/"):
        login_user(test_user)
        client = socketio.test_client(app)
        assert client.is_connected()

        client.emit("join", {"room": convo_id})

        plan_steps = ["Step 1", "Step 2"]
        set_plan(steps=plan_steps, conversation_id=convo_id)

        # Poll for the event with a timeout
        import time

        start_time = time.time()
        received = []
        while time.time() - start_time < 5:
            received = client.get_received()
            if any(e["name"] == "plan_updated" for e in received):
                break
            socketio.sleep(0.1)

        assert any(
            e["name"] == "plan_updated" for e in received
        ), "Did not receive 'plan_updated' event."

        plan_update_event = next(e for e in received if e["name"] == "plan_updated")
        assert plan_update_event["args"][0]["steps"] == plan_steps

        client.disconnect()


def test_write_file_emits_refresh(app, socketio, test_user, mocker):
    """
    Tests that the write_file tool emits a 'refresh_files' event.
    """
    from tools import write_file

    convo_id = "refresh_test_convo"

    # Mock get_workspace_path to prevent file system operations
    mocker.patch('tools.file_system.get_workspace_path', return_value='/tmp')
    mocker.patch('os.makedirs')
    mocker.patch('builtins.open', mocker.mock_open())


    with app.test_request_context("/"):
        login_user(test_user)
        client = socketio.test_client(app)
        assert client.is_connected()

        client.emit("join", {"room": convo_id})

        write_file(path="test.txt", content="hello", conversation_id=convo_id, user_id=test_user.id)

        # Poll for the event with a timeout
        import time
        start_time = time.time()
        received = []
        while time.time() - start_time < 5:
            received = client.get_received()
            if any(e["name"] == "refresh_files" for e in received):
                break
            socketio.sleep(0.1)

        assert any(e["name"] == "refresh_files" for e in received), "Did not receive 'refresh_files' event."

        refresh_event = next(e for e in received if e["name"] == "refresh_files")
        assert refresh_event["args"][0]["conversation_id"] == convo_id

        client.disconnect()


def test_tree_of_thoughts_multiple_tool_calls(app, test_user, mocker):
    """
    Tests that the new Tree of Thoughts logic can parse and execute multiple
    tool calls from a single AI response.
    """
    mock_stream = mocker.patch("chat.call_ollama_chat_stream")
    mock_handle_tool_call = mocker.patch("chat.handle_tool_call")
    mocker.patch("chat.update_conversation_title")

    # AI response with two distinct tool calls
    multi_tool_response = """
    <think>
    I have two hypotheses.
    Hypothesis 1: The user wants to list files.
    Hypothesis 2: The user wants to know the database schema.
    </think>
    ```json
    {
        "tool": "list_files",
        "parameters": {}
    }
    ```
    ```json
    {
        "tool": "get_db_schema",
        "parameters": {}
    }
    ```
    """
    final_answer = "I have performed both actions."

    mock_stream.side_effect = [
        iter([multi_tool_response]),
        iter([final_answer]),
    ]
    # Mock the results from the tool calls
    mock_handle_tool_call.side_effect = [
        ("file1.txt\nfile2.txt", False),  # Result for list_files
        ("Table: users(id, name)", False),  # Result for get_db_schema
    ]

    with app.test_request_context('/api/chat?messages=[{"role":"user","content":"list files and show schema"}]'):
        login_user(test_user)
        from chat import chat_proxy
        response = chat_proxy()

        events = [json.loads(line.replace("data: ", "")) for line in response.response if line]

        tool_call_events = [e for e in events if e["type"] == "tool_call"]
        tool_result_events = [e for e in events if e["type"] == "tool_result"]

        # Assert that two tool calls were made
        assert len(tool_call_events) == 2
        assert tool_call_events[0]["name"] == "list_files"
        assert tool_call_events[1]["name"] == "get_db_schema"

        # Assert that two tool results were received
        assert len(tool_result_events) == 2
        assert "file1.txt" in tool_result_events[0]["result"]
        assert "Table: users" in tool_result_events[1]["result"]

        # Assert that the handle_tool_call mock was called twice
        assert mock_handle_tool_call.call_count == 2
