import json
from unittest.mock import MagicMock
from flask_login import login_user


def test_full_chat_with_tool_call(app, test_user, mocker):
    """
    Tests a full chat conversation with a tool call.
    """
    # 1. Mock the `requests.post` call to the Ollama API.
    mock_post = mocker.patch("requests.post")

    # Canned responses from the mocked Ollama API.
    tool_call_response = {
        "message": {
            "content": (
                "<think>I need to list the files in the "
                "workspace.</think>```json\n"
                '{\n    "tool": "list_files",\n    "parameters": {}\n}\n```'
            )
        }
    }
    final_answer_response = {
        "message": {
            "content": "I have listed the files for you."
        }
    }
    title_generation_response = {
        "message": {
            "content": "List Files"
        }
    }

    # Set up the mock to return the responses in order.
    mock_post.side_effect = [
        MagicMock(iter_content=lambda chunk_size: [
            (json.dumps(tool_call_response) + '\n').encode("utf-8")
        ]),
        MagicMock(iter_content=lambda chunk_size: [
            (json.dumps(final_answer_response) + '\n').encode("utf-8")
        ]),
        MagicMock(json=lambda: title_generation_response)
    ]

    # 2. Call the chat_proxy function directly within a request context.
    with app.test_request_context(
        '/api/chat?messages=[{"role":"user","content":"list the files"}]'
        '&model=test-model'
    ):
        # Manually log in the test user.
        login_user(test_user)

        from routes import chat_proxy
        response = chat_proxy()

        # 3. Assert the response stream contains the expected events.
        assert response.status_code == 200

        events = [
            json.loads(line.replace("data: ", ""))
            for line in response.response if line
        ]

        assert events[0]["type"] == "conversation_id"
        assert events[1]["type"] == "assistant_chunk"
        assert events[2]["type"] == "assistant_end"
        assert events[3]["type"] == "tool_result"
        assert events[4]["type"] == "assistant_chunk"
        assert events[5]["type"] == "assistant_end"
        assert events[6]["type"] == "final_answer"
        assert events[7]["type"] == "done"
        assert events[7]["title"] == "List Files"
