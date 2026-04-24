import json
import os
from types import SimpleNamespace

import tools.runtime as runtime
from os_safety import list_pending_approvals, resolve_approval_request
from task_runner import BackgroundTaskRunner, execute_task_instruction
from telegram_router import create_pairing_code, complete_pairing


def _conversation_and_user():
    return {"id": "c-safety", "owner_id": 1, "project_id": None}, SimpleNamespace(id=1, username="testuser")


def _workflow_file(instance_path, user_id=1, action_type="click"):
    path = os.path.join(instance_path, str(user_id), "workflows.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "workflows": [
            {
                "workflow_id": "wf-1",
                "name": "Safety Workflow",
                "description": "for tests",
                "run_count": 0,
                "success_count": 0,
                "success_rate": 0,
                "steps": [
                    {
                        "step_id": "s1",
                        "action_type": action_type,
                        "parameters": {"button": "left"} if action_type == "click" else {"title": "x"},
                        "context": {},
                        "verification_rule": {},
                        "fallback_hints": [],
                        "visual_anchor": {},
                    }
                ],
            }
        ],
        "recording_sessions": {},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_os_tools_blocked_when_os_agent_disabled(app, mocker):
    app.config.update(OS_AGENT_ENABLED=False)
    conversation, user = _conversation_and_user()
    with app.app_context():
        normalized = runtime.normalize_tool_call({"tool": "click", "parameters": {"button": "left"}})
        result = runtime.execute_normalized_tool_call(
            normalized,
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
    assert result["error_type"] == "os_tool_safety_block"


def test_standard_mode_blocks_action_tools(app):
    app.config.update(OS_AGENT_ENABLED=True, OS_AGENT_SAFE_MODE=False)
    conversation, user = _conversation_and_user()
    with app.app_context():
        for tool_call in [
            {"tool": "click", "parameters": {"button": "left"}},
            {"tool": "type_text", "parameters": {"text": "hello"}},
            {"tool": "open_app", "parameters": {"name": "Calculator"}},
            {"tool": "run_workflow", "parameters": {"workflow_id": "wf-1"}},
        ]:
            normalized = runtime.normalize_tool_call(tool_call)
            result = runtime.execute_normalized_tool_call(
                normalized,
                conversation,
                user,
                execution_context={"mode": "standard", "os_control_enabled": True, "explicit_user_intent": True},
            )
            assert result["error_type"] == "os_tool_safety_block"


def test_observe_tool_available_when_allowed(app, mocker):
    app.config.update(OS_AGENT_ENABLED=True, OS_AGENT_SAFE_MODE=False)

    def fake_capture(**_kwargs):
        return {"status": "success"}

    registry = {
        "capture_screen": runtime.ToolDefinition(
            "capture_screen", "cap", {}, [], [], False, fake_capture, model_visible=True, safety_category="observe"
        )
    }
    mocker.patch("tools.runtime.TOOL_REGISTRY", registry)
    conversation, user = _conversation_and_user()
    with app.app_context():
        normalized = runtime.normalize_tool_call({"tool": "capture_screen", "parameters": {}})
        result = runtime.execute_normalized_tool_call(
            normalized,
            conversation,
            user,
            execution_context={"mode": "standard", "os_control_enabled": False, "explicit_user_intent": False},
        )
    assert result["status"] == "success"


def test_caution_and_dangerous_require_approval(app, mocker):
    app.config.update(
        OS_AGENT_ENABLED=True,
        OS_AGENT_SAFE_MODE=True,
        OS_AGENT_REQUIRE_APPROVAL_FOR_CAUTION=True,
        OS_AGENT_REQUIRE_APPROVAL_FOR_DANGEROUS=True,
    )

    def noop(**_kwargs):
        return {"status": "success"}

    registry = {
        "click": runtime.ToolDefinition("click", "click", {"button": "str"}, [], ["button"], False, noop),
        "close_window": runtime.ToolDefinition("close_window", "close", {"title": "str"}, ["title"], [], False, noop),
    }
    mocker.patch("tools.runtime.TOOL_REGISTRY", registry)

    conversation, user = _conversation_and_user()
    with app.app_context():
        caution = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "click", "parameters": {"button": "left"}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
        dangerous = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "close_window", "parameters": {"title": "x"}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )

    assert caution["status"] == "pending_approval"
    assert dangerous["status"] == "pending_approval"


def test_approved_executes_and_rejected_stays_blocked(app, mocker):
    app.config.update(OS_AGENT_ENABLED=True, OS_AGENT_SAFE_MODE=True, OS_AGENT_REQUIRE_APPROVAL_FOR_CAUTION=True)

    def noop(**_kwargs):
        return {"status": "success"}

    registry = {
        "click": runtime.ToolDefinition("click", "click", {"button": "str"}, [], ["button"], False, noop),
    }
    mocker.patch("tools.runtime.TOOL_REGISTRY", registry)
    conversation, user = _conversation_and_user()

    with app.app_context():
        first = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "click", "parameters": {"button": "left"}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
        req_id = first["result"]["approval_request"]["request_id"]
        resolve_approval_request(app.instance_path, req_id, status="approved", resolved_by=1)

        approved = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "click", "parameters": {"button": "left"}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
        assert approved["status"] == "success"

        second = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "click", "parameters": {"button": "right"}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
        reject_id = second["result"]["approval_request"]["request_id"]
        resolve_approval_request(app.instance_path, reject_id, status="rejected", resolved_by=1)
        blocked = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "click", "parameters": {"button": "right"}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
    assert blocked["status"] == "pending_approval"


def test_model_visible_docs_hide_disallowed_tools(app):
    app.config.update(OS_AGENT_ENABLED=False)
    with app.app_context():
        docs = runtime.render_model_visible_tool_docs(mode="standard", os_control_enabled=False)
    assert "click(" not in docs
    assert "open_app(" not in docs


def test_workflow_replay_stops_on_unsafe_step(app):
    app.config.update(OS_AGENT_ENABLED=True, OS_AGENT_SAFE_MODE=False)
    _workflow_file(app.instance_path, 1, action_type="close_window")

    with app.app_context():
        result = runtime.run_workflow(
            workflow_id="wf-1",
            user_id=1,
            execution_context={"mode": "deep", "os_control_enabled": True, "explicit_user_intent": True, "source": "test"},
        )
    assert result["status"] == "error"
    assert result["results"][0]["error_type"] == "os_tool_safety_block"


def test_telegram_run_workflow_obeys_safety_gate(app):
    app.config.update(OS_AGENT_ENABLED=False)
    _workflow_file(app.instance_path, 1, action_type="click")
    pair = create_pairing_code(app.instance_path, user_id=1, expiry_seconds=120)
    complete_pairing(app.instance_path, telegram_user_id=8111, telegram_username="u", code=pair["pairing_code"])

    message = execute_task_instruction(app, 1, "workflow:wf-1")
    assert message["status"] in {"error", "pending_approval"}


def test_background_workflow_task_cannot_bypass_safety(app):
    app.config.update(OS_AGENT_ENABLED=False)
    _workflow_file(app.instance_path, 1, action_type="click")
    runner = BackgroundTaskRunner(app, socketio=None)
    task = {
        "task_id": "wf-task",
        "user_id": 1,
        "task_type": "workflow",
        "payload": {"workflow_id": "wf-1", "approved": True},
    }
    result, _ = runner._run_workflow_task(task)
    assert result["status"] == "error"
    assert result["details"]["error_type"] == "os_tool_safety_block"


def test_pending_approvals_endpoint_flow(logged_in_client, app):
    app.config.update(OS_AGENT_ENABLED=True, OS_AGENT_SAFE_MODE=True, OS_AGENT_REQUIRE_APPROVAL_FOR_CAUTION=True)
    conversation, user = _conversation_and_user()
    with app.app_context():
        runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "click", "parameters": {"button": "left"}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
        assert list_pending_approvals(app.instance_path, user_id=1)

    pending_resp = logged_in_client.get("/api/os-approvals/pending")
    assert pending_resp.status_code == 200
    approvals = pending_resp.get_json()["approvals"]
    assert approvals

    req_id = approvals[0]["request_id"]
    approve_resp = logged_in_client.post(f"/api/os-approvals/{req_id}", json={"decision": "approve"})
    assert approve_resp.status_code == 200


def test_screenshot_request_disabled_returns_policy_block(app):
    app.config.update(OS_AGENT_ENABLED=False)
    conversation, user = _conversation_and_user()
    with app.app_context():
        result = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "capture_screen", "parameters": {}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
    assert result["error_type"] == "os_tool_safety_block"


def test_screenshot_request_requires_approval_when_configured(app, mocker):
    app.config.update(
        OS_AGENT_ENABLED=True,
        OS_AGENT_SAFE_MODE=True,
        OS_AGENT_REQUIRE_APPROVAL_FOR_OBSERVE=True,
    )

    def fake_capture(**_kwargs):
        return {"status": "success", "image_path": "/tmp/shot.png"}

    mocker.patch(
        "tools.runtime.TOOL_REGISTRY",
        {"capture_screen": runtime.ToolDefinition("capture_screen", "capture", {}, [], [], False, fake_capture)},
    )
    conversation, user = _conversation_and_user()
    with app.app_context():
        result = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "capture_screen", "parameters": {}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
    assert result["status"] == "pending_approval"


def test_screenshot_request_approval_granted_executes(app, mocker):
    app.config.update(
        OS_AGENT_ENABLED=True,
        OS_AGENT_SAFE_MODE=True,
        OS_AGENT_REQUIRE_APPROVAL_FOR_OBSERVE=True,
    )

    def fake_capture(**_kwargs):
        return {"status": "success", "image_path": "/tmp/shot.png"}

    mocker.patch(
        "tools.runtime.TOOL_REGISTRY",
        {"capture_screen": runtime.ToolDefinition("capture_screen", "capture", {}, [], [], False, fake_capture)},
    )
    conversation, user = _conversation_and_user()
    with app.app_context():
        pending = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "capture_screen", "parameters": {}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
        req_id = pending["result"]["approval_request"]["request_id"]
        resolve_approval_request(app.instance_path, req_id, status="approved", resolved_by=1)
        executed = runtime.execute_normalized_tool_call(
            runtime.normalize_tool_call({"tool": "capture_screen", "parameters": {}}),
            conversation,
            user,
            execution_context={"mode": "agent", "os_control_enabled": True, "explicit_user_intent": True},
        )
    assert executed["status"] == "success"
