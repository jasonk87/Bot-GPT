from unittest.mock import MagicMock

import prompts
import tools.runtime as runtime


def _sample_value(param_type):
    samples = {
        "str": "value",
        "int": 1,
        "float": 1.0,
        "bool": True,
        "list": [],
        "dict": {},
    }
    return samples[param_type]


def test_prompt_docs_match_model_visible_definitions():
    docs = runtime.render_model_visible_tool_docs()
    assert docs in prompts.DEFAULT_SYSTEM_PROMPT
    for definition in runtime.get_model_visible_tool_definitions():
        assert f"`{definition.name}(" in docs


def test_internal_runtime_helpers_are_not_model_visible():
    docs = runtime.render_model_visible_tool_docs()
    hidden_names = [
        "normalize_tool_call",
        "normalize_and_prepare_tool_calls",
        "dedupe_normalized_tool_calls",
        "execute_normalized_tool_call",
        "handle_tool_call",
    ]
    for name in hidden_names:
        assert name not in docs


def test_every_model_visible_definition_has_executable_handler():
    for definition in runtime.get_model_visible_tool_definitions():
        assert definition.handler is not None
        assert callable(definition.handler)


def test_documented_required_and_optional_params_match_validation():
    for definition in runtime.get_model_visible_tool_definitions():
        params = {}
        for key in definition.required_fields:
            params[key] = _sample_value(definition.parameter_schema[key])
        normalized = runtime.normalize_tool_call({"tool": definition.name, "parameters": params})
        assert normalized.validation_status == "valid"

        for optional_key in definition.optional_fields:
            optional_params = dict(params)
            optional_params[optional_key] = _sample_value(definition.parameter_schema[optional_key])
            optional_normalized = runtime.normalize_tool_call(
                {"tool": definition.name, "parameters": optional_params}
            )
            assert optional_normalized.validation_status == "valid"


def test_known_contract_drift_cases_are_fixed():
    pip_call = runtime.normalize_tool_call({"tool": "pip", "parameters": {"command": "install pytest"}})
    assert pip_call.validation_status == "valid"

    debugger_call = runtime.normalize_tool_call(
        {
            "tool": "ask_debugger",
            "parameters": {"failed_command": "pytest -q", "error_message": "stack trace"},
        }
    )
    assert debugger_call.validation_status == "valid"

    git_pull_call = runtime.normalize_tool_call({"tool": "git_pull", "parameters": {"repo_path": "."}})
    assert git_pull_call.validation_status == "valid"


def test_documented_contract_call_validates_and_executes(mocker):
    mocker.patch(
        "tools.runtime.current_app",
        MagicMock(config={"USER_DATA_DIR": "/tmp", "GOOGLE_API_KEY": "", "GOOGLE_CSE_ID": ""}),
    )
    conversation = {"id": "c1", "owner_id": 1, "project_id": None}
    user = MagicMock(id=1)
    normalized = runtime.normalize_tool_call(
        {"tool": "read_core_file", "parameters": {"path": "prompts.py"}}
    )
    execution = runtime.execute_normalized_tool_call(normalized, conversation, user)
    assert execution["status"] == "success"
    assert isinstance(execution["result"], str)


def test_prompt_generation_stays_readable():
    docs = runtime.render_model_visible_tool_docs()
    lines = [line for line in docs.splitlines() if line.strip()]
    assert lines
    assert all(line.startswith("- `") for line in lines)


def test_prompt_includes_tool_outcome_retry_discipline_rules():
    prompt = prompts.DEFAULT_SYSTEM_PROMPT
    assert "Tool Outcome Discipline" in prompt
    assert "partial_success" in prompt
    assert "retryable=false" in prompt
    assert "Do not repeat an identical call after a non-retryable failure." in prompt


def test_prompt_includes_tool_selection_cost_tiers_and_escalation():
    prompt = prompts.DEFAULT_SYSTEM_PROMPT
    assert "LOW COST / NARROW" in prompt
    assert "MEDIUM COST / TARGETED" in prompt
    assert "HIGH COST / BROAD" in prompt
    assert "narrow -> targeted -> broad" in prompt
    assert "Choose the minimal sufficient tool first" in prompt


def test_prompt_includes_intent_plan_continuity_guidance():
    prompt = prompts.DEFAULT_SYSTEM_PROMPT
    assert "Intent / Plan Continuity" in prompt
    assert "objective and sub-goal" in prompt
    assert "ready_to_answer" in prompt


def test_prompt_includes_mode_aware_expectations():
    prompt = prompts.DEFAULT_SYSTEM_PROMPT
    assert "Mode-Aware Execution Expectations" in prompt
    assert "Standard mode" in prompt
    assert "Deep mode" in prompt
    assert "Agent mode" in prompt
