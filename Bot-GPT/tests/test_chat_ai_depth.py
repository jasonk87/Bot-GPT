import json
from unittest.mock import MagicMock

import chat_ai


def test_determine_depth_mode_defaults_to_standard_for_simple_prompt():
    messages = [{"role": "user", "content": "Give me a concise answer."}]
    mode, source = chat_ai.determine_depth_mode(messages)
    assert mode == "standard"
    assert source in {"heuristic_fallback", "model_router", "low_confidence_fallback"}


def test_determine_depth_mode_deep_signal():
    messages = [{"role": "user", "content": "Can you give me a detailed step-by-step plan?"}]
    mode, _ = chat_ai.determine_depth_mode(messages)
    assert mode == "deep"


def test_determine_depth_mode_defaults_to_standard():
    messages = [{"role": "user", "content": "What are your thoughts on this architecture?"}]
    mode, _ = chat_ai.determine_depth_mode(messages)
    assert mode == "standard"


def test_determine_depth_mode_auto_triggers_deep_on_complex_prompt():
    messages = [{
        "role": "user",
        "content": "Can you compare options and propose an architecture strategy with tradeoffs and implementation steps for this migration?",
    }]
    mode, _ = chat_ai.determine_depth_mode(messages)
    assert mode == "deep"


def test_determine_depth_mode_respects_explicit_preference():
    messages = [{"role": "user", "content": "Simple answer please."}]
    assert chat_ai.determine_depth_mode(messages, preference="deep") == ("deep", "user_preference")
    assert chat_ai.determine_depth_mode(messages, preference="standard") == ("standard", "user_preference")


def test_determine_depth_mode_uses_model_router_when_available():
    messages = [{"role": "user", "content": "Should we compare architectural options and tradeoffs?"}]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter(['{"mode":"deep","confidence":0.92}'])

    mode, source = chat_ai.determine_depth_mode(messages, preference="auto", model="test-model", call_stream=fake_call_stream)
    assert mode == "deep"
    assert source == "model_router"


def test_merge_persistent_messages_keeps_session_summary():
    existing = [
        {"role": "system", "content": "Session memory summary: user prefers concise updates"},
        {"role": "assistant", "content": "Older answer"},
    ]
    incoming = [{"role": "user", "content": "What did I just ask you to do?"}]

    merged = chat_ai._merge_persistent_messages(existing, incoming)

    assert merged[0]["role"] == "system"
    assert merged[0]["content"].startswith("Session memory summary:")
    assert merged[-1] == incoming[0]


def test_determine_depth_mode_low_confidence_falls_back_to_heuristics():
    messages = [{"role": "user", "content": "Could you do a deep dive into architecture options and tradeoffs?"}]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter(['{"mode":"standard","confidence":0.42}'])

    mode, source = chat_ai.determine_depth_mode(messages, preference="auto", model="test-model", call_stream=fake_call_stream)
    assert mode == "deep"
    assert source == "low_confidence_fallback"


def test_handle_ai_response_emits_response_mode_and_injects_depth_prompt(mocker):
    captured_system_prompt = {}

    def fake_call_stream(model, messages, system_prompt):
        captured_system_prompt["value"] = system_prompt
        return iter(["Short answer."])

    mock_init = MagicMock()
    conversation = {"id": "c1", "owner_id": 1, "messages": []}
    mock_init.return_value = ("test-model", "BASE SYSTEM", conversation, "/tmp/convo.json")

    mock_update_title = MagicMock()
    mock_save = mocker.patch("chat_ai.save_conversation")
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())
    mocker.patch(
        "chat_ai.get_selected_repository",
        return_value={
            "name": "sample-repo",
            "path": "/tmp/sample-repo",
            "primary_languages": ["Python"],
            "preferred_preview_target": "app.py",
            "entry_points": ["app.py"],
        },
    )

    events = list(
        chat_ai.handle_ai_response(
            {
                "messages": json.dumps([{"role": "user", "content": "Give me a concise answer"}]),
                "model": "test-model",
                "conversation_id": "",
                "response_mode_preference": "deep",
            },
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda calls: [],
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=lambda calls, conversation, user: {"status": "empty", "policy": "continue_on_error_in_order", "success_count": 0, "error_count": 0, "results": []},
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=mock_update_title,
            write_file=MagicMock(),
        )
    )

    response_modes = [event for event in events if event.get("type") == "response_mode"]
    assert response_modes == [{"type": "response_mode", "mode": "deep", "source": "user_preference"}]
    progress_events = [event for event in events if event.get("type") == "progress_update"]
    assert any(event.get("stage") == "planning" for event in progress_events)
    assert any(event.get("stage") == "executing" for event in progress_events)
    assert any(event.get("stage") == "verifying" for event in progress_events)
    assert any(event.get("stage") == "finalizing" for event in progress_events)
    assert "Response depth: Deep" in captured_system_prompt["value"]
    assert "INTENT CONTINUITY STATE" in captured_system_prompt["value"]
    assert "REPOSITORY CONTEXT" in captured_system_prompt["value"]
    assert "Do not append a literal 'Next step:' line to your conversational responses" in captured_system_prompt["value"]
    assert mock_save.called


def test_handle_ai_response_executes_canvas_autofix_action(mocker):
    mock_init = MagicMock()
    conversation = {"id": "c-canvas-fix", "owner_id": 1, "messages": []}
    mock_init.return_value = ("test-model", "BASE SYSTEM", conversation, "/tmp/convo.json")
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai.current_app", MagicMock())
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    execute_batch = MagicMock(return_value={
        "status": "success",
        "policy": "continue_on_error_in_order",
        "success_count": 1,
        "error_count": 0,
        "results": [{
            "tool_name": "implement_and_test_code",
            "status": "success",
            "result": "Success! Code implemented and passed tests.",
            "retryable": False,
            "validation_status": "valid",
            "error_type": None,
            "error_message": None,
        }],
    })

    events = list(
        chat_ai.handle_ai_response(
            {
                "messages": json.dumps([{"role": "user", "content": "auto-fix this file"}]),
                "model": "test-model",
                "conversation_id": "",
                "canvas_mode": True,
                "canvas_action": {
                    "tool": "implement_and_test_code",
                    "parameters": {
                        "target_file": "main.py",
                        "test_command": "python main.py",
                        "task_description": "fix script from stderr",
                        "max_iterations": 2,
                    },
                },
            },
            initialize_chat=mock_init,
            call_stream=lambda *_: iter(["unused"]),
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda calls: calls,
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=execute_batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(return_value={"status": "file_written", "path": "canvas.py"}),
        )
    )

    assert execute_batch.called
    tool_calls = [event for event in events if event.get("type") == "tool_call"]
    assert tool_calls and tool_calls[0]["name"] == "implement_and_test_code"
    assert any(event.get("type") == "done" for event in events)


def test_ensure_next_step_line_no_longer_forces_suffix_when_missing():
    content = chat_ai.ensure_next_step_line("Here is a concise answer.")
    assert content == "Here is a concise answer."


def test_ensure_next_step_line_keeps_existing_next_step():
    content = "Summary complete.\n\nNext step: Run the tests."
    assert chat_ai.ensure_next_step_line(content) == content


def test_ensure_next_step_line_removes_empty_next_step():
    content = "Summary complete.\n\nNext step:None"
    assert chat_ai.ensure_next_step_line(content) == "Summary complete."


def test_messages_for_persistence_keeps_only_final_visible_assistant_answer():
    messages = [
        {"role": "user", "content": "What's on the news today?"},
        {"role": "assistant", "content": "```json\n{\"tool\":\"web_search\",\"parameters\":{\"query\":\"news\"}}\n```"},
        {"role": "tool", "content": "TOOL BATCH RESULT"},
        {"role": "assistant", "content": "Here's a complete news summary."},
    ]

    persisted = chat_ai._messages_for_persistence(messages)

    assert persisted == [
        {"role": "user", "content": "What's on the news today?"},
        {"role": "assistant", "content": "Here's a complete news summary."},
    ]


def test_messages_for_persistence_drops_thinking_only_assistant_message():
    messages = [
        {"role": "user", "content": "Think about this."},
        {"role": "assistant", "content": "<think>internal reasoning only</think>"},
    ]

    assert chat_ai._messages_for_persistence(messages) == [
        {"role": "user", "content": "Think about this."},
    ]


def test_messages_for_persistence_drops_punctuation_only_assistant_message():
    messages = [
        {"role": "user", "content": "Try again"},
        {"role": "assistant", "content": "."},
    ]

    assert chat_ai._messages_for_persistence(messages) == [
        {"role": "user", "content": "Try again"},
    ]


def test_handle_ai_response_emits_structured_batch_tool_feedback(mocker):
    class DummyCall:
        def __init__(self, name, params):
            self.tool_name = name
            self.normalized_params = params
            self.validation_status = "valid"
            self.source_metadata = {"index": 0}

    stream_responses = [
        '```json\n{"tool":"write_file","parameters":{"path":"a.txt"}}\n```',
        "Done.",
    ]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter([stream_responses.pop(0)])

    conversation = {"id": "c1", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch(
        "chat_ai._extract_tool_calls",
        side_effect=[
            [{"tool": "write_file", "parameters": {"path": "a.txt"}}],
            [],
        ],
    )
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())

    normalized_calls = [DummyCall("write_file", {"path": "a.txt"}), DummyCall("write_file", {"path": "b.txt"})]
    batch = {
        "status": "partial_success",
        "policy": "continue_on_error_in_order",
        "success_count": 1,
        "error_count": 1,
        "results": [
            {"tool_name": "write_file", "status": "success", "result": {"status": "file_written", "path": "a.txt"}, "error_type": None, "error_message": None, "retryable": False},
            {"tool_name": "write_file", "status": "error", "result": None, "error_type": "validation_error", "error_message": "bad param", "retryable": False},
        ],
    }

    events = list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "do files"}]), "model": "test-model", "conversation_id": "", "response_mode_preference": "deep"},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda calls: normalized_calls,
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=lambda calls, convo, user, **kwargs: batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )

    result_events = [e for e in events if e.get("type") == "tool_result"]
    error_events = [e for e in events if e.get("type") == "tool_error"]
    activity_events = [e for e in events if e.get("type") == "activity_update"]
    assert len(result_events) == 1
    assert len(error_events) == 1
    assert len(activity_events) >= 1
    assert "meta" in result_events[0]
    assert "meta" in error_events[0]
    assert "[validation_error] bad param (retryable=False)" in error_events[0]["error"]


def test_loop_guard_blocks_identical_non_retryable_repeat(mocker):
    class DummyCall:
        def __init__(self, name, params):
            self.tool_name = name
            self.normalized_params = params
            self.validation_status = "valid"
            self.source_metadata = {"index": 0}

    stream_responses = [
        '```json\n{"tool":"write_file","parameters":{"path":"same.txt"}}\n```',
        '```json\n{"tool":"write_file","parameters":{"path":"same.txt"}}\n```',
        "done",
    ]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter([stream_responses.pop(0)])

    call = DummyCall("write_file", {"path": "same.txt"})
    mock_batch = MagicMock(
        side_effect=[
            {
                "status": "error",
                "policy": "continue_on_error_in_order",
                "success_count": 0,
                "error_count": 1,
                "results": [
                    {"tool_name": "write_file", "status": "error", "result": None, "error_type": "execution_error", "error_message": "permission denied", "retryable": False, "validation_status": "valid", "source_metadata": {"index": 0}},
                ],
            },
            {
                "status": "empty",
                "policy": "continue_on_error_in_order",
                "success_count": 0,
                "error_count": 0,
                "results": [],
            },
        ]
    )

    conversation = {"id": "c-loop", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai._extract_tool_calls", side_effect=[[{"tool": "write_file", "parameters": {"path": "same.txt"}}], [{"tool": "write_file", "parameters": {"path": "same.txt"}}], []])
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())

    events = list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "do it"}]), "model": "test-model", "conversation_id": ""},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda calls: [call],
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=mock_batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )

    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert any("loop_guard_non_retryable_repeat" in e.get("error", "") for e in error_events)
    assert mock_batch.call_count == 2


def test_format_tool_batch_feedback_contains_recovery_fields():
    content = chat_ai._format_tool_batch_feedback(
        {"status": "partial_success", "policy": "continue_on_error_in_order", "success_count": 1, "error_count": 1},
        [
            {"tool_name": "read_file", "status": "success", "result": {"status": "ok", "path": "a.txt"}, "retryable": False, "validation_status": "valid", "error_type": None, "error_message": None, "source_metadata": {"index": 0}},
            {"tool_name": "write_file", "status": "error", "result": None, "retryable": False, "validation_status": "valid", "error_type": "execution_error", "error_message": "permission denied", "source_metadata": {"index": 1}},
        ],
    )
    assert "batch_status" in content
    assert "tool_name" in content
    assert "retryable" in content
    assert "error_type" in content
    assert "usefulness_hint" in content


def test_redundant_identical_success_call_is_blocked_in_same_context(mocker):
    class DummyCall:
        def __init__(self, name, params):
            self.tool_name = name
            self.normalized_params = params
            self.validation_status = "valid"
            self.source_metadata = {"index": 0}

    stream_responses = [
        '```json\n{"tool":"list_files","parameters":{"path":"."}}\n```',
        '```json\n{"tool":"list_files","parameters":{"path":"."}}\n```',
        "done",
    ]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter([stream_responses.pop(0)])

    call = DummyCall("list_files", {"path": "."})
    mock_batch = MagicMock(
        side_effect=[
            {
                "status": "success",
                "policy": "continue_on_error_in_order",
                "success_count": 1,
                "error_count": 0,
                "results": [
                    {"tool_name": "list_files", "status": "success", "result": ["a.txt"], "error_type": None, "error_message": None, "retryable": False, "validation_status": "valid", "source_metadata": {"index": 0}},
                ],
            },
            {
                "status": "empty",
                "policy": "continue_on_error_in_order",
                "success_count": 0,
                "error_count": 0,
                "results": [],
            },
        ]
    )

    conversation = {"id": "c-redundant", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai._extract_tool_calls", side_effect=[[{"tool": "list_files", "parameters": {"path": "."}}], [{"tool": "list_files", "parameters": {"path": "."}}], []])
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())

    events = list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "list files"}]), "model": "test-model", "conversation_id": "", "response_mode_preference": "deep"},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda calls: [call],
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=mock_batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )

    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert any("redundant_call_same_context" in e.get("error", "") for e in error_events)


def test_intent_state_initializes_from_latest_user_objective():
    state = chat_ai._initialize_intent_state(
        [{"role": "assistant", "content": "x"}, {"role": "user", "content": "Fix the failing migration tests"}]
    )
    assert state["objective"] == "Fix the failing migration tests"
    assert state["ready_to_answer"] is False


def test_intent_state_updates_on_success_and_partial_progress():
    class DummyCall:
        def __init__(self, name, params):
            self.tool_name = name
            self.normalized_params = params

    state = chat_ai._initialize_intent_state([{"role": "user", "content": "Audit auth bug"}])
    calls = [DummyCall("read_file", {"path": "a.py"}), DummyCall("run_shell_command", {"command": "pytest -q"})]
    results = [
        {"status": "success", "retryable": False, "error_type": None},
        {"status": "error", "retryable": False, "error_type": "execution_error"},
    ]
    updated = chat_ai._update_intent_state(state, calls, results, {"status": "partial_success"})
    assert any("Completed: read_file" in item for item in updated["completed_items"])
    assert any("Blocked: run_shell_command" in item for item in updated["blocked_items"])
    assert updated["ready_to_answer"] is True
    assert "successful branches" in updated["current_focus"]


def test_intent_state_empty_batch_updates_next_hint():
    state = chat_ai._initialize_intent_state([{"role": "user", "content": "Summarize logs"}])
    updated = chat_ai._update_intent_state(state, [], [], {"status": "empty"})
    assert "No executable calls" in updated["next_step_hint"]


def test_mode_profile_sets_budget_and_branch_limits():
    standard = chat_ai._mode_profile("standard", False)
    deep = chat_ai._mode_profile("deep", False)
    agent = chat_ai._mode_profile("standard", True)
    assert standard["tool_batch_budget"] == 2
    assert standard["branch_limit"] == 2
    assert deep["branch_limit"] == 3
    assert agent["tool_batch_budget"] is None


def test_agent_phase_helpers_exist():
    assert hasattr(chat_ai, "agent_plan_phase")
    assert hasattr(chat_ai, "agent_act_phase")
    assert hasattr(chat_ai, "agent_verify_phase")
    assert hasattr(chat_ai, "agent_decide_phase")


def test_agent_verify_phase_injects_deterministic_repair_directive(mocker):
    mocker.patch(
        "chat_ai._run_verification_loop",
        return_value={
            "status": "failed",
            "summary": "pytest failed",
            "pending_failure": {
                "classification": "import_error",
                "command": "pytest -q",
                "summary": "ModuleNotFoundError",
            },
        },
    )
    conversation = {"messages": []}
    state = {"pending_failure": None, "attempts": 0, "max_attempts": 3, "last_summary": ""}

    report = chat_ai.agent_verify_phase(
        changed_paths=["a.py"],
        messages=[{"role": "user", "content": "fix code"}],
        conversation=conversation,
        verification_state=state,
    )

    assert report["status"] == "failed"
    assert state["pending_failure"]["classification"] == "import_error"
    directives = [m for m in conversation["messages"] if m.get("role") == "tool" and "DETERMINISTIC REPAIR DIRECTIVE" in m.get("content", "")]
    assert directives


def test_agent_decide_phase_returns_unable_to_verify_on_failed_execution():
    decision = chat_ai.agent_decide_phase(
        profile={"mode": "standard"},
        intent_state={"ready_to_answer": True},
        batch_outcome={"status": "partial_success"},
        verification_state={"pending_failure": {"classification": "test_failure"}, "attempts": 3, "max_attempts": 3},
        aggregated_tool_results=[
            {
                "tool_name": "run_shell_command",
                "status": "error",
                "error_type": "nonzero_exit",
            }
        ],
    )
    assert decision["action"] == "unable_to_verify"
    assert "unable to verify" in decision["reason"].lower()


def test_agent_decide_phase_breaks_when_validation_allows():
    decision = chat_ai.agent_decide_phase(
        profile={"mode": "standard"},
        intent_state={"ready_to_answer": True},
        batch_outcome={"status": "success"},
        verification_state={"pending_failure": None},
        aggregated_tool_results=[{"tool_name": "read_file", "status": "success"}],
    )
    assert decision["action"] == "break"


def test_standard_mode_allows_two_branches_per_batch(mocker):
    class DummyCall:
        def __init__(self, name, params):
            self.tool_name = name
            self.normalized_params = params
            self.validation_status = "valid"
            self.source_metadata = {"index": 0}

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter(['```json\n{"tool":"list_files","parameters":{"path":"."}}\n```'])

    calls = [DummyCall("list_files", {"path": "."}), DummyCall("read_file", {"path": "a.py"})]
    execute_batch = MagicMock(return_value={"status": "success", "policy": "continue_on_error_in_order", "success_count": 2, "error_count": 0, "results": [
        {"tool_name": "list_files", "status": "success", "result": [], "retryable": False, "validation_status": "valid", "error_type": None, "error_message": None},
        {"tool_name": "read_file", "status": "success", "result": "content", "retryable": False, "validation_status": "valid", "error_type": None, "error_message": None},
    ]})
    conversation = {"id": "c-branch", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai._extract_tool_calls", side_effect=[[{"tool": "list_files", "parameters": {"path": "."}}], []])
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())

    list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "quick check"}]), "model": "test-model", "conversation_id": "", "response_mode_preference": "standard"},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda _: calls,
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=execute_batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )
    assert len(execute_batch.call_args[0][0]) == 2


def test_standard_mode_tool_batch_budget_fast_exit(mocker):
    class DummyCall:
        def __init__(self):
            self.tool_name = "list_files"
            self.normalized_params = {"path": "."}
            self.validation_status = "valid"
            self.source_metadata = {"index": 0}

    stream_responses = [
        '```json\n{"tool":"list_files","parameters":{"path":"."}}\n```',
        '```json\n{"tool":"list_files","parameters":{"path":"."}}\n```',
        '```json\n{"tool":"list_files","parameters":{"path":"."}}\n```',
    ]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter([stream_responses.pop(0)]) if stream_responses else iter(["done"])

    execute_batch = MagicMock(return_value={"status": "error", "policy": "continue_on_error_in_order", "success_count": 0, "error_count": 1, "results": [{"tool_name": "list_files", "status": "error", "result": None, "retryable": True, "validation_status": "valid", "error_type": "execution_error", "error_message": "temporary timeout"}]})
    conversation = {"id": "c-budget", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai._extract_tool_calls", side_effect=[[{"tool": "list_files", "parameters": {"path": "."}}], [{"tool": "list_files", "parameters": {"path": "."}}], [{"tool": "list_files", "parameters": {"path": "."}}], []])
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())

    list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "quick check"}]), "model": "test-model", "conversation_id": "", "response_mode_preference": "standard"},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda _: [DummyCall()],
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=execute_batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )
    assert execute_batch.call_count == 2


def test_verification_loop_continues_until_pass_or_blocked(mocker):
    class DummyCall:
        def __init__(self, content):
            self.tool_name = "write_file"
            self.normalized_params = {"path": "a.py", "content": content}
            self.validation_status = "valid"
            self.source_metadata = {"index": 0}

    stream_responses = [
        '```json\n{"tool":"write_file","parameters":{"path":"a.py","content":"v1"}}\n```',
        '```json\n{"tool":"write_file","parameters":{"path":"a.py","content":"v2"}}\n```',
        "final",
    ]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter([stream_responses.pop(0)])

    conversation = {"id": "c-verify", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai.current_app", MagicMock(instance_path="/tmp"))
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch(
        "chat_ai._extract_tool_calls",
        side_effect=[
            [{"tool": "write_file", "parameters": {"path": "a.py", "content": "v1"}}],
            [{"tool": "write_file", "parameters": {"path": "a.py", "content": "v2"}}],
            [],
        ],
    )
    mocker.patch(
        "chat_ai._run_verification_loop",
        side_effect=[
            {
                "status": "failed",
                "summary": "Verification results: FAIL",
                "pending_failure": {"classification": "syntax_error", "step_type": "lint", "command": "python -m py_compile a.py"},
            },
            {
                "status": "passed",
                "summary": "Verification results: PASS",
                "pending_failure": None,
            },
        ],
    )

    batch = {
        "status": "success",
        "policy": "continue_on_error_in_order",
        "success_count": 1,
        "error_count": 0,
        "results": [{
            "tool_name": "write_file",
            "status": "success",
            "result": {"status": "file_written", "path": "a.py", "content": "v"},
            "retryable": False,
            "validation_status": "valid",
            "error_type": None,
            "error_message": None,
        }],
    }

    events = list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "Fix and verify fully"}]), "model": "test-model", "conversation_id": ""},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda calls: [DummyCall("v")],
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=lambda *_args, **_kwargs: batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )

    actions = [e.get("last_action", "") for e in events if e.get("type") == "activity_update"]
    assert any("Verification failed" in action for action in actions)
    assert any("Verification passed" in action for action in actions)
    assert any(e.get("type") == "done" for e in events)


def test_tool_batch_feedback_preserves_web_search_content():
    long_search_answer = "Today's News Headlines\n\n" + "\n".join(
        f"- Headline {idx}: detail" for idx in range(80)
    )
    feedback = chat_ai._format_tool_batch_feedback(
        {"status": "success", "policy": "continue_on_error_in_order", "success_count": 1, "error_count": 0},
        [{
            "tool_name": "web_search",
            "status": "success",
            "retryable": False,
            "validation_status": "valid",
            "error_type": None,
            "error_message": None,
            "result": long_search_answer,
        }],
    )

    assert "result_content" in feedback
    assert "Headline 79: detail" in feedback
    assert "Tool output truncated" not in feedback


def test_search_needed_text_forces_web_search_tool(mocker):
    class DummyCall:
        def __init__(self, name, params):
            self.tool_name = name
            self.normalized_params = params
            self.validation_status = "valid"
            self.source_metadata = {"index": 0}

    stream_responses = [
        "To find the answer, I need to search for information specifically about Ark Survival Ascended.",
        "The update is for Ark: Survival Ascended and is expected on a specific announced date.",
    ]

    def fake_call_stream(_model, _messages, _system_prompt):
        return iter([stream_responses.pop(0)])

    normalized_seen = []

    def normalize(calls):
        normalized_seen.append(calls)
        return [DummyCall(call["tool"], call.get("parameters", {})) for call in calls]

    execute_batch = MagicMock(return_value={
        "status": "success",
        "policy": "continue_on_error_in_order",
        "success_count": 1,
        "error_count": 0,
        "results": [{
            "tool_name": "web_search",
            "status": "success",
            "result": "Search result: Ark Survival Ascended update release date details.",
            "retryable": False,
            "validation_status": "valid",
            "error_type": None,
            "error_message": None,
        }],
    })
    conversation = {"id": "c-search-needed", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai.estimate_context_usage", return_value=0)
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())

    events = list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "Actually it'll be for ark survival ascended"}]), "model": "test-model", "conversation_id": "", "response_mode_preference": "standard"},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=normalize,
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=execute_batch,
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )

    assert normalized_seen[0][0]["tool"] == "web_search"
    assert "ark survival ascended" in normalized_seen[0][0]["parameters"]["query"].lower()
    assert any(event.get("type") == "tool_call" and event.get("name") == "web_search" for event in events)
    assert any(event.get("type") == "final_answer" and "Ark: Survival Ascended" in event.get("content", "") for event in events)


def test_hidden_only_response_gets_visible_fallback(mocker):
    def fake_call_stream(_model, _messages, _system_prompt):
        return iter(["<think>still thinking</think>"])

    conversation = {"id": "c-hidden-only", "owner_id": 1, "messages": []}
    mock_init = MagicMock(return_value=("test-model", "BASE", conversation, "/tmp/convo.json"))
    mocker.patch("chat_ai.save_conversation")
    mocker.patch("chat_ai.estimate_context_usage", return_value=0)
    mock_current_user = mocker.patch("chat_ai.current_user")
    mock_current_user.id = 1
    mocker.patch("chat_ai.current_app", MagicMock())

    events = list(
        chat_ai.handle_ai_response(
            {"messages": json.dumps([{"role": "user", "content": "When is it coming out?"}]), "model": "test-model", "conversation_id": "", "response_mode_preference": "standard"},
            initialize_chat=mock_init,
            call_stream=fake_call_stream,
            handle_tool_call=MagicMock(),
            normalize_and_prepare_tool_calls=lambda calls: [],
            execute_normalized_tool_call=MagicMock(),
            execute_tool_call_batch=MagicMock(),
            sanitize_json=lambda s: s,
            agent_sessions={},
            update_conversation_title=MagicMock(),
            write_file=MagicMock(),
        )
    )

    final_answers = [event.get("content", "") for event in events if event.get("type") == "final_answer"]
    assert final_answers
    assert "couldn't produce a usable final answer" in final_answers[-1]
