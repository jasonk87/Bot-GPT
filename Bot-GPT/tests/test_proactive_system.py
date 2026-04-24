import os
import threading
import time

from task_runner import BackgroundTaskRunner
from task_scheduler import (
    compute_next_run,
    create_task,
    list_tasks,
    mark_task_result,
)
from notification_router import (
    decide_route,
    get_user_activity,
    mark_user_activity,
)
from memory_store import list_facts


def test_task_scheduling_interval_and_cron(app):
    now = 1_700_000_000
    interval_next = compute_next_run({"type": "interval", "every_minutes": 5}, now)
    cron_next = compute_next_run({"type": "cron", "expression": "*/10 * * * *"}, now)
    assert int(interval_next - now) == 300
    assert int(cron_next - now) == 600


def test_task_state_updates_last_run_and_next_run(app):
    task = create_task(
        app.instance_path,
        1,
        {
            "name": "interval",
            "description": "tick",
            "task_type": "periodic_check",
            "schedule": {"type": "interval", "every_seconds": 60},
            "payload": {"value": "alpha"},
        },
    )
    updated = mark_task_result(app.instance_path, 1, task["task_id"], {"status": "ok", "message": "ran"})
    assert updated["last_run"] is not None
    assert updated["next_run"] > updated["last_run"]


def test_result_evaluation_notify_vs_silent(app):
    runner = BackgroundTaskRunner(app, socketio=None, poll_interval_seconds=1, max_concurrent_tasks=2)
    task = {
        "task_id": "t1",
        "user_id": 1,
        "name": "Monitor",
        "task_type": "monitor",
        "payload": {"value": "same"},
        "conditions": {"notify_on_change": True},
        "last_result": {"details": {"observed_value": "same"}},
    }
    result, should_notify = runner._run_monitor_task(task)
    assert result["details"]["changed"] is False
    assert should_notify is False

    task["payload"] = {"value": "new"}
    result2, should_notify2 = runner._run_monitor_task(task)
    assert result2["details"]["changed"] is True
    assert should_notify2 is True


def test_memory_integration_for_task_results(app):
    runner = BackgroundTaskRunner(app, socketio=None)
    task = {"task_id": "m1", "user_id": 1, "name": "Repo check"}
    result = {"message": "no changes detected"}
    with app.app_context():
        runner._persist_task_memory(task, result)
        facts = list_facts(1)
    assert any(f.get("key") == "proactive_task::m1" for f in facts)


def test_notification_routing_prefers_active_ui(app):
    instance_path = app.instance_path
    mark_user_activity(instance_path, 1, channel="ui")
    assert decide_route(instance_path, 1, idle_threshold_seconds=120) == "active_ui"

    stale = get_user_activity(instance_path, 1)
    stale["last_active_at"] = time.time() - 3600
    activity_path = os.path.join(instance_path, "1", "activity_state.json")
    os.makedirs(os.path.dirname(activity_path), exist_ok=True)
    with open(activity_path, "w", encoding="utf-8") as handle:
        import json

        json.dump(stale, handle)
    assert decide_route(instance_path, 1, idle_threshold_seconds=60) == "stored"


def test_per_user_task_isolation(app):
    create_task(
        app.instance_path,
        1,
        {
            "name": "u1",
            "description": "d",
            "task_type": "reminder",
            "schedule": {"type": "interval", "every_seconds": 60},
        },
    )
    create_task(
        app.instance_path,
        2,
        {
            "name": "u2",
            "description": "d",
            "task_type": "reminder",
            "schedule": {"type": "interval", "every_seconds": 60},
        },
    )
    user1_tasks = list_tasks(app.instance_path, 1)
    user2_tasks = list_tasks(app.instance_path, 2)
    assert all(task["user_id"] == 1 for task in user1_tasks)
    assert all(task["user_id"] == 2 for task in user2_tasks)


def test_concurrency_limit_respected(app, monkeypatch):
    runner = BackgroundTaskRunner(app, socketio=None, poll_interval_seconds=0.01, max_concurrent_tasks=2)

    due_tasks = [
        {"task_id": f"t{i}", "user_id": 1, "status": "active", "next_run": 0, "task_type": "reminder", "name": "n"}
        for i in range(4)
    ]

    collect_calls = {"count": 0}
    peak = {"value": 0}
    current = {"value": 0}
    lock = threading.Lock()

    def fake_collect():
        collect_calls["count"] += 1
        if collect_calls["count"] > 2:
            runner._stop_event.set()
        return due_tasks

    def fake_execute(_task):
        with lock:
            current["value"] += 1
            peak["value"] = max(peak["value"], current["value"])
        time.sleep(0.03)
        with lock:
            current["value"] -= 1

    monkeypatch.setattr(runner, "_collect_due_tasks", fake_collect)
    monkeypatch.setattr(runner, "_execute_task_safe", fake_execute)

    thread = threading.Thread(target=runner._run_loop, daemon=True)
    thread.start()
    thread.join(timeout=1)

    assert peak["value"] <= 2


def test_task_routes_and_heartbeat_endpoint(logged_in_client):
    create_resp = logged_in_client.post(
        "/api/tasks",
        json={
            "name": "Lunch reminder",
            "description": "Remind me at lunch",
            "task_type": "reminder",
            "schedule": {"type": "interval", "every_minutes": 30},
            "payload": {"message": "It is lunch time."},
        },
    )
    assert create_resp.status_code == 201

    list_resp = logged_in_client.get("/api/tasks")
    assert list_resp.status_code == 200
    tasks = list_resp.get_json()["tasks"]
    assert tasks

    heartbeat_resp = logged_in_client.get("/api/system/heartbeat")
    assert heartbeat_resp.status_code == 200
    assert "last_heartbeat" in heartbeat_resp.get_json()
