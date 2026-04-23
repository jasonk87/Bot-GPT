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
    assert "Always end your final user-facing response" in captured_system_prompt["value"]
    assistant_chunks = [event for event in events if event.get("type") == "assistant_chunk"]
    assert any("Next step:" in event["content"] for event in assistant_chunks)
    assert mock_save.called


def test_ensure_next_step_line_adds_suffix_when_missing():
    content = chat_ai.ensure_next_step_line("Here is a concise answer.")
    assert "Next step:" in content


def test_ensure_next_step_line_keeps_existing_next_step():
    content = "Summary complete.\n\nNext step: Run the tests."
    assert chat_ai.ensure_next_step_line(content) == content
