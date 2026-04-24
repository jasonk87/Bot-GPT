from workflow_learning import (
    finalize_recording_session,
    list_workflows,
    record_workflow_step,
    replay_workflow,
    select_best_workflow,
    start_recording_session,
)
from task_runner import execute_task_instruction


def test_workflow_recording_and_structure(app):
    session_id = start_recording_session(app.instance_path, 1, name="Email check", description="Open mail and verify inbox")
    step = record_workflow_step(
        app.instance_path,
        1,
        session_id,
        action_type="open_url",
        parameters={"url": "https://mail.example.com"},
        context={"what_changed": "mail page opened"},
        verification_rule={"expected_text": "Inbox"},
        fallback_hints=[{"action_type": "open_url", "parameters": {"url": "https://mail.example.com/login"}}],
    )
    assert step["action_type"] == "open_url"
    assert "verification_rule" in step

    record_workflow_step(
        app.instance_path,
        1,
        session_id,
        action_type="click_element",
        parameters={"text": "Inbox"},
        context={"what_changed": "inbox selected"},
        verification_rule={"expected_text": "Unread"},
    )

    workflow = finalize_recording_session(app.instance_path, 1, session_id, successful=True, min_steps_to_record=2)
    assert workflow is not None
    assert workflow["name"] == "Email check"
    assert len(workflow["steps"]) == 2


def test_failed_or_short_recordings_not_saved(app):
    session = start_recording_session(app.instance_path, 1)
    record_workflow_step(
        app.instance_path,
        1,
        session,
        action_type="click",
        parameters={"button": "left"},
    )
    assert finalize_recording_session(app.instance_path, 1, session, successful=True, min_steps_to_record=2) is None


def test_replay_order_verification_and_fallback(app):
    session = start_recording_session(app.instance_path, 1, name="Test Flow")
    record_workflow_step(
        app.instance_path,
        1,
        session,
        action_type="click",
        parameters={"button": "left", "target_text": "Submit"},
        verification_rule={"expected_text": "Done"},
        fallback_hints=[{"action_type": "click_element", "parameters": {"text": "Submit"}}],
    )
    record_workflow_step(
        app.instance_path,
        1,
        session,
        action_type="type_text",
        parameters={"text": "hello"},
        verification_rule={"expected_text": "hello"},
    )
    workflow = finalize_recording_session(app.instance_path, 1, session, successful=True, min_steps_to_record=2)

    calls = []

    def click(**kwargs):
        calls.append(("click", kwargs))
        return {"status": "error", "message": "missed"}

    def click_element(**kwargs):
        calls.append(("click_element", kwargs))
        return {"status": "success"}

    def type_text(**kwargs):
        calls.append(("type_text", kwargs))
        return {"status": "success"}

    verifier_state = {"count": 0}

    def verifier():
        verifier_state["count"] += 1
        if verifier_state["count"] < 3:
            return "Not done"
        return "Done hello"

    result = replay_workflow(
        app.instance_path,
        1,
        workflow["workflow_id"],
        executors={"click": click, "click_element": click_element, "type_text": type_text, "move_mouse": lambda **k: {"status": "success"}},
        verifier=verifier,
        max_steps=10,
    )
    assert result["status"] == "success"
    assert calls[0][0] == "click"
    assert any(c[0] == "click_element" for c in calls)


def test_workflow_selection_logic(app):
    session = start_recording_session(app.instance_path, 1, name="Repo sync workflow", description="sync repository and verify clean status")
    record_workflow_step(app.instance_path, 1, session, action_type="open_url", parameters={"url": "https://git.example.com"})
    record_workflow_step(app.instance_path, 1, session, action_type="click_element", parameters={"text": "Sync"})
    wf = finalize_recording_session(app.instance_path, 1, session, successful=True, min_steps_to_record=2)

    match = select_best_workflow(app.instance_path, 1, "run repo sync")
    assert match is not None
    assert match["workflow_id"] == wf["workflow_id"]


def test_per_user_isolation(app):
    s1 = start_recording_session(app.instance_path, 1, name="User1 only")
    record_workflow_step(app.instance_path, 1, s1, action_type="open_url", parameters={"url": "https://a"})
    record_workflow_step(app.instance_path, 1, s1, action_type="click_element", parameters={"text": "x"})
    finalize_recording_session(app.instance_path, 1, s1, successful=True, min_steps_to_record=2)

    assert list_workflows(app.instance_path, 2) == []


def test_task_and_telegram_workflow_trigger(app, monkeypatch):
    session = start_recording_session(app.instance_path, 1, name="Email check")
    record_workflow_step(app.instance_path, 1, session, action_type="open_url", parameters={"url": "https://mail"})
    record_workflow_step(app.instance_path, 1, session, action_type="click_element", parameters={"text": "Inbox"})
    workflow = finalize_recording_session(app.instance_path, 1, session, successful=True, min_steps_to_record=2)

    monkeypatch.setattr(
        "tools.runtime.run_workflow",
        lambda workflow_id, user_id=None, **kwargs: {"status": "success", "workflow_id": workflow_id, "results": []},
    )
    response = execute_task_instruction(app, 1, f"workflow:{workflow['workflow_id']}")
    assert response["status"] == "success"


def test_workflow_management_endpoints(logged_in_client, app, monkeypatch):
    session = start_recording_session(app.instance_path, 1, name="UI flow")
    record_workflow_step(app.instance_path, 1, session, action_type="open_url", parameters={"url": "https://x"})
    record_workflow_step(app.instance_path, 1, session, action_type="click_element", parameters={"text": "Go"})
    workflow = finalize_recording_session(app.instance_path, 1, session, successful=True, min_steps_to_record=2)

    list_resp = logged_in_client.get("/api/workflows")
    assert list_resp.status_code == 200
    assert any(w["workflow_id"] == workflow["workflow_id"] for w in list_resp.get_json()["workflows"])

    monkeypatch.setattr(
        "tools.runtime.run_workflow",
        lambda workflow_id, user_id=None, **kwargs: {"status": "success", "workflow_id": workflow_id, "results": []},
    )
    run_resp = logged_in_client.post(f"/api/workflows/{workflow['workflow_id']}/run")
    assert run_resp.status_code == 200

    delete_resp = logged_in_client.delete(f"/api/workflows/{workflow['workflow_id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.get_json()["removed"] is True
