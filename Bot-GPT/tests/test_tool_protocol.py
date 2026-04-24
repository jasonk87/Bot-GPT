from types import SimpleNamespace
from unittest.mock import MagicMock

import tools.runtime as runtime


def _patch_registry(mocker, *, required_fields=None, optional_fields=None, allow_unknown=False):
    required_fields = required_fields or []
    optional_fields = optional_fields or []

    def fake_handler(path, conversation_id=None, user_id=None):
        return {"status": "ok", "path": path, "conversation_id": conversation_id, "user_id": user_id}

    registry = {
        "write_file": runtime.ToolDefinition(
            name="write_file",
            description="Write file for test",
            parameter_schema={"path": "str"},
            required_fields=required_fields,
            optional_fields=optional_fields,
            allow_unknown_fields=allow_unknown,
            handler=fake_handler,
        )
    }
    mocker.patch("tools.runtime.TOOL_REGISTRY", registry)
    return fake_handler


def _conversation_and_user():
    conversation = {"id": "c1", "owner_id": 100, "project_id": None}
    user = SimpleNamespace(id=200)
    return conversation, user


def test_valid_known_tool_executes_successfully(mocker):
    _patch_registry(mocker, required_fields=["path"])
    mocker.patch("tools.runtime.current_app", MagicMock(config={"USER_DATA_DIR": "/tmp", "GOOGLE_API_KEY": "", "GOOGLE_CSE_ID": ""}))
    conversation, user = _conversation_and_user()

    normalized = runtime.normalize_tool_call({"tool": "write_file", "parameters": {"path": "a.txt"}})
    result = runtime.execute_normalized_tool_call(normalized, conversation, user)

    assert result["status"] == "success"
    assert result["tool_name"] == "write_file"
    assert result["result"]["path"] == "a.txt"


def test_unknown_tool_is_rejected(mocker):
    _patch_registry(mocker, required_fields=["path"])
    normalized = runtime.normalize_tool_call({"tool": "nope", "parameters": {"path": "a.txt"}})
    assert normalized.validation_status == "invalid"
    assert "Unknown tool" in normalized.validation_errors[0]


def test_missing_required_param_is_rejected(mocker):
    _patch_registry(mocker, required_fields=["path"])
    normalized = runtime.normalize_tool_call({"tool": "write_file", "parameters": {}})
    assert normalized.validation_status == "invalid"
    assert "Missing required parameter 'path'." in normalized.validation_errors


def test_wrong_param_type_is_rejected(mocker):
    _patch_registry(mocker, required_fields=["path"])
    normalized = runtime.normalize_tool_call({"tool": "write_file", "parameters": {"path": 123}})
    assert normalized.validation_status == "invalid"
    assert any("Invalid type for 'path'" in err for err in normalized.validation_errors)


def test_unknown_extra_param_is_rejected_when_disallowed(mocker):
    _patch_registry(mocker, required_fields=["path"], allow_unknown=False)
    normalized = runtime.normalize_tool_call(
        {"tool": "write_file", "parameters": {"path": "a.txt", "extra": "nope"}}
    )
    assert normalized.validation_status == "invalid"
    assert any("Unknown parameter(s): extra." == err for err in normalized.validation_errors)


def test_duplicate_semantically_identical_calls_are_deduped(mocker):
    _patch_registry(mocker, required_fields=["path"])
    deduped = runtime.normalize_and_prepare_tool_calls(
        [
            {"tool": "write_file", "parameters": {"path": "a.txt"}},
            {"tool": "write_file", "parameters": {"path": "a.txt"}},
        ]
    )
    assert len(deduped) == 1


def test_mixed_valid_and_invalid_calls_execute_deterministically(mocker):
    _patch_registry(mocker, required_fields=["path"])
    mocker.patch("tools.runtime.current_app", MagicMock(config={"USER_DATA_DIR": "/tmp", "GOOGLE_API_KEY": "", "GOOGLE_CSE_ID": ""}))
    conversation, user = _conversation_and_user()
    normalized = runtime.normalize_and_prepare_tool_calls(
        [
            {"tool": "write_file", "parameters": {"path": "a.txt"}},
            {"tool": "write_file", "parameters": {"path": 123}},
        ]
    )

    results = [runtime.execute_normalized_tool_call(call, conversation, user) for call in normalized]
    statuses = [item["status"] for item in results]
    assert statuses.count("success") == 1
    assert statuses.count("error") == 1


def test_execution_layer_requires_normalized_protocol_object(mocker):
    _patch_registry(mocker, required_fields=["path"])
    conversation, user = _conversation_and_user()
    result = runtime.execute_normalized_tool_call({"tool": "write_file"}, conversation, user)
    assert result["status"] == "error"
    assert result["error_type"] == "protocol_error"


def test_batch_all_valid_success(mocker):
    _patch_registry(mocker, required_fields=["path"])
    mocker.patch("tools.runtime.current_app", MagicMock(config={"USER_DATA_DIR": "/tmp", "GOOGLE_API_KEY": "", "GOOGLE_CSE_ID": ""}))
    conversation, user = _conversation_and_user()
    normalized_calls = runtime.normalize_and_prepare_tool_calls(
        [
            {"tool": "write_file", "parameters": {"path": "a.txt"}},
            {"tool": "write_file", "parameters": {"path": "b.txt"}},
        ]
    )
    batch = runtime.execute_tool_call_batch(normalized_calls, conversation, user)
    assert batch["status"] == "success"
    assert batch["success_count"] == 2
    assert batch["error_count"] == 0


def test_batch_mixed_invalid_and_valid_continues_in_order(mocker):
    _patch_registry(mocker, required_fields=["path"])
    mocker.patch("tools.runtime.current_app", MagicMock(config={"USER_DATA_DIR": "/tmp", "GOOGLE_API_KEY": "", "GOOGLE_CSE_ID": ""}))
    conversation, user = _conversation_and_user()
    normalized_calls = runtime.normalize_and_prepare_tool_calls(
        [
            {"tool": "write_file", "parameters": {"path": "a.txt"}},
            {"tool": "write_file", "parameters": {"path": 1}},
        ]
    )
    batch = runtime.execute_tool_call_batch(normalized_calls, conversation, user)
    assert batch["policy"] == "continue_on_error_in_order"
    assert batch["status"] == "partial_success"
    assert [item["status"] for item in batch["results"]] == ["success", "error"]


def test_execution_exception_sets_retryable_for_transient_errors(mocker):
    def flaky(path, conversation_id=None, user_id=None):
        raise RuntimeError("connection timeout to backend service")

    registry = {
        "write_file": runtime.ToolDefinition(
            name="write_file",
            description="Write file for test",
            parameter_schema={"path": "str"},
            required_fields=["path"],
            optional_fields=[],
            allow_unknown_fields=False,
            handler=flaky,
        )
    }
    mocker.patch("tools.runtime.TOOL_REGISTRY", registry)
    mocker.patch("tools.runtime.current_app", MagicMock(config={"USER_DATA_DIR": "/tmp", "GOOGLE_API_KEY": "", "GOOGLE_CSE_ID": ""}))
    conversation, user = _conversation_and_user()
    normalized = runtime.normalize_tool_call({"tool": "write_file", "parameters": {"path": "a.txt"}})
    result = runtime.execute_normalized_tool_call(normalized, conversation, user)
    assert result["status"] == "error"
    assert result["retryable"] is True


def test_validation_failure_keeps_structured_fields(mocker):
    _patch_registry(mocker, required_fields=["path"])
    normalized = runtime.normalize_tool_call({"tool": "write_file", "parameters": {"path": 1}})
    conversation, user = _conversation_and_user()
    result = runtime.execute_normalized_tool_call(normalized, conversation, user)
    assert result["status"] == "error"
    assert result["validation_status"] == "invalid"
    assert isinstance(result["source_metadata"], dict)
