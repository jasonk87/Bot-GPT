import json
import os
import time

from memory_store import list_facts
from notification_router import build_notification, route_notification
from task_scheduler import create_task
from telegram_router import (
    complete_pairing,
    create_pairing_code,
    get_local_user_for_telegram,
    handle_telegram_command,
)


class DummyBridge:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def _expire_all_challenges(instance_path):
    path = os.path.join(instance_path, "telegram_pairing.json")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    for challenge in payload.get("challenges", []):
        challenge["expires_at"] = time.time() - 1
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def test_pairing_flow_valid_and_invalid_and_expired(app):
    pair = create_pairing_code(app.instance_path, user_id=1, expiry_seconds=120)

    ok, _, local_user = complete_pairing(app.instance_path, telegram_user_id=7001, telegram_username="alice", code=pair["pairing_code"])
    assert ok is True
    assert local_user == 1
    assert get_local_user_for_telegram(app.instance_path, 7001) == 1

    # code is single-use
    ok2, message2, _ = complete_pairing(app.instance_path, telegram_user_id=7002, telegram_username="bob", code=pair["pairing_code"])
    assert ok2 is False
    assert "Invalid or expired" in message2

    pair2 = create_pairing_code(app.instance_path, user_id=2, expiry_seconds=60)
    _expire_all_challenges(app.instance_path)
    ok3, message3, _ = complete_pairing(app.instance_path, telegram_user_id=7003, telegram_username="eve", code=pair2["pairing_code"])
    assert ok3 is False
    assert "Invalid or expired" in message3


def test_command_routing_and_memory_integration(app):
    pair = create_pairing_code(app.instance_path, user_id=1, expiry_seconds=120)
    complete_pairing(app.instance_path, telegram_user_id=8001, telegram_username="owner", code=pair["pairing_code"])

    create_task(
        app.instance_path,
        1,
        {
            "name": "Reminder A",
            "description": "test",
            "task_type": "reminder",
            "schedule": {"type": "interval", "every_seconds": 60},
            "payload": {"message": "hello"},
        },
    )

    status_msg = handle_telegram_command(app, 8001, "owner", "/status")
    assert "System status" in status_msg

    tasks_msg = handle_telegram_command(app, 8001, "owner", "/tasks")
    assert "Reminder A" in tasks_msg

    run_msg = handle_telegram_command(app, 8001, "owner", "/run status")
    assert "Remote instruction executed" in run_msg

    with app.app_context():
        facts = list_facts(1)
    assert any("telegram_command::" in fact.get("key", "") for fact in facts)


def test_per_user_isolation_for_telegram_commands(app):
    pair1 = create_pairing_code(app.instance_path, user_id=1, expiry_seconds=120)
    pair2 = create_pairing_code(app.instance_path, user_id=2, expiry_seconds=120)
    complete_pairing(app.instance_path, telegram_user_id=9001, telegram_username="u1", code=pair1["pairing_code"])
    complete_pairing(app.instance_path, telegram_user_id=9002, telegram_username="u2", code=pair2["pairing_code"])

    create_task(
        app.instance_path,
        1,
        {
            "name": "U1 Task",
            "description": "x",
            "task_type": "reminder",
            "schedule": {"type": "interval", "every_seconds": 60},
        },
    )
    create_task(
        app.instance_path,
        2,
        {
            "name": "U2 Task",
            "description": "x",
            "task_type": "reminder",
            "schedule": {"type": "interval", "every_seconds": 60},
        },
    )

    msg1 = handle_telegram_command(app, 9001, "u1", "/tasks")
    msg2 = handle_telegram_command(app, 9002, "u2", "/tasks")
    assert "U1 Task" in msg1 and "U2 Task" not in msg1
    assert "U2 Task" in msg2 and "U1 Task" not in msg2


def test_notification_bridge_active_vs_inactive(app):
    pair = create_pairing_code(app.instance_path, user_id=1, expiry_seconds=120)
    complete_pairing(app.instance_path, telegram_user_id=9991, telegram_username="notify", code=pair["pairing_code"])

    bridge = DummyBridge()
    note = build_notification(user_id=1, task_id="abc123", title="Repo Monitor", message="New commit detected")

    # active UI => no telegram send
    activity_path = os.path.join(app.instance_path, "1", "activity_state.json")
    os.makedirs(os.path.dirname(activity_path), exist_ok=True)
    with open(activity_path, "w", encoding="utf-8") as handle:
        json.dump({"last_active_at": time.time(), "channel": "ui"}, handle)
    route1 = route_notification(app.instance_path, socketio=None, notification=note, telegram_bridge=bridge)
    assert route1 == "active_ui" or route1 == "stored"
    assert bridge.sent == []

    # inactive => telegram fallback
    with open(activity_path, "w", encoding="utf-8") as handle:
        json.dump({"last_active_at": time.time() - 3600, "channel": "ui"}, handle)
    route2 = route_notification(app.instance_path, socketio=None, notification=note, telegram_bridge=bridge)
    assert route2 == "stored+telegram"
    assert bridge.sent


def test_unpaired_user_cannot_execute_commands(app):
    msg = handle_telegram_command(app, telegram_user_id=4401, telegram_username="stranger", text="/status")
    assert "not paired" in msg
