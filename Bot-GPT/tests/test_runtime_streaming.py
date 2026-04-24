import os

from tools import get_workspace_path
from tools.shell import run_shell_command
from tools import runtime


def test_run_shell_command_streams_output_lines(app, test_user):
    streamed = []
    with app.app_context():
        workspace_path = get_workspace_path(conversation_id="stream-1", owner_id=test_user.id)
        target = os.path.join(workspace_path, "stream.txt")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("line-one\nline-two\n")

        result = run_shell_command(
            "cat stream.txt",
            conversation_id="stream-1",
            user_id=test_user.id,
            user=test_user,
            stream_callback=lambda stream, line: streamed.append((stream, line)),
        )

    assert "line-one" in result
    assert "line-two" in result
    assert ("stdout", "line-one") in streamed
    assert ("stdout", "line-two") in streamed


def test_execute_python_emits_tool_stream_events(app, test_user, mocker):
    with app.app_context():
        workspace_path = get_workspace_path(conversation_id="stream-2", owner_id=test_user.id)
        script_path = os.path.join(workspace_path, "emit.py")
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(
                "import sys\n"
                "print('alpha')\n"
                "print('beta')\n"
                "sys.stderr.write('warn\\n')\n"
            )

        emit_mock = mocker.patch("tools.runtime.socketio.emit")
        result = runtime.execute_python("emit.py", conversation_id="stream-2", user_id=test_user.id, timeout=5)

    assert "alpha" in result
    assert "beta" in result
    assert "warn" in result
    stream_events = [
        call.args[1]
        for call in emit_mock.call_args_list
        if call.args and call.args[0] == "ai_response" and isinstance(call.args[1], dict) and call.args[1].get("type") == "tool_stream"
    ]
    assert any(event.get("content") == "alpha" for event in stream_events)
    assert any(event.get("content") == "beta" for event in stream_events)
    assert any(event.get("stream") == "stderr" for event in stream_events)
