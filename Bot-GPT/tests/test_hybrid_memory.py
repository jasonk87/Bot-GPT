from context_compactor import compact_session_history, estimate_context_usage
from memory_ingest import extract_facts_from_message, is_memory_worthy
from memory_retriever import build_memory_injection_block, retrieve_relevant_memory, build_user_memory_block
from memory_store import upsert_fact, list_facts, update_session_memory
from chat_persistence import initialize_chat
from flask_login import login_user
from models import User


def test_memory_ingestion_stores_relevant_facts(app, test_user):
    with app.app_context():
        facts = extract_facts_from_message("I prefer Python and my repo alpha-service has a gateway.")
        assert len(facts) >= 1
        for fact in facts:
            upsert_fact(
                test_user.id,
                scope=fact["scope"],
                key=fact["key"],
                value=fact["value"],
                source_conversation_id="c1",
                source_message_index=3,
                confidence=fact["confidence"],
                project_key="alpha" if fact["scope"] == "project" else None,
            )
        stored = list_facts(test_user.id, scope="user")
        assert len(stored) >= 1


def test_irrelevant_data_is_not_memory_worthy():
    assert is_memory_worthy("hi") is False
    assert extract_facts_from_message("ok") == []
    assert is_memory_worthy("AI Cannot Access Desktop") is False
    assert is_memory_worthy("assistant: I am a language model") is False


def test_name_statements_are_extracted_as_identity_facts():
    facts = extract_facts_from_message("My name is Alice")
    assert any(fact["key"] == "identity:name" and fact["value"] == "Alice" for fact in facts)


def test_retrieval_returns_relevant_items(app, test_user):
    with app.app_context():
        upsert_fact(
            test_user.id,
            scope="user",
            key="preference:python",
            value="User prefers Python for backend work.",
            source_conversation_id="c2",
            source_message_index=0,
            confidence=0.9,
        )
        retrieved = retrieve_relevant_memory(test_user.id, "python backend preference")
        assert retrieved["user_facts"]
        assert "python" in retrieved["user_facts"][0]["value"].lower()


def test_memory_injection_is_bounded_and_traceable(app, test_user):
    with app.app_context():
        upsert_fact(
            test_user.id,
            scope="user",
            key="ownership:truck",
            value="User owns a truck.",
            source_conversation_id="c-trace",
            source_message_index=8,
            confidence=0.8,
        )
        block = build_memory_injection_block(test_user.id, "c-trace", "truck", max_chars=300)
        assert len(block) <= 300
        assert "source: convo=c-trace" in block


def test_per_user_memory_isolation(app, two_users):
    user1, user2 = two_users
    with app.app_context():
        upsert_fact(
            user1.id,
            scope="user",
            key="pref:one",
            value="User one prefers Go.",
            source_conversation_id="c-u1",
            source_message_index=1,
            confidence=0.7,
        )
        upsert_fact(
            user2.id,
            scope="user",
            key="pref:two",
            value="User two prefers Rust.",
            source_conversation_id="c-u2",
            source_message_index=1,
            confidence=0.7,
        )
        user1_facts = list_facts(user1.id, scope="user")
        user2_facts = list_facts(user2.id, scope="user")
    assert any("Go" in f["value"] for f in user1_facts)
    assert all("Rust" not in f["value"] for f in user1_facts)
    assert any("Rust" in f["value"] for f in user2_facts)


def test_context_compaction_preserves_key_info():
    messages = [{"role": "user", "content": "todo: fix parser"} for _ in range(20)]
    usage = estimate_context_usage(messages, max_chars=100)
    assert usage > 0.7
    compacted = compact_session_history(messages, keep_recent=5)
    assert compacted["summary"]
    assert len(compacted["trimmed_messages"]) == 5
    assert compacted["key_notes"]


def test_session_memory_updates(app, test_user):
    with app.app_context():
        update_session_memory(test_user.id, "conv-1", "summary text", ["note-a", "note-b"])
        block = build_memory_injection_block(test_user.id, "conv-1", "summary")
    assert "summary text" in block


def test_user_memory_block_is_explicit_and_stable(test_user):
    block = build_user_memory_block(test_user)
    assert block.startswith("=== USER MEMORY ===")
    assert f"username: {test_user.username}" in block
    assert "This is trusted user identity memory. Use it when relevant." in block
    assert block.strip().endswith("===================")


def test_user_memory_block_maps_jasonk87_to_display_name(app):
    with app.app_context():
        upsert_fact(
            10,
            scope="user",
            key="identity:display_name",
            value="Jason",
            source_conversation_id="seed",
            source_message_index=0,
            confidence=0.95,
        )
        user = User(id=10, username="jasonk87", password_hash=None)
        block = build_user_memory_block(user)
    assert "display_name: Jason" in block


def test_user_memory_block_does_not_hardcode_jason_mapping():
    user = User(id=11, username="jasonk87", password_hash=None)
    block = build_user_memory_block(user)
    assert "display_name: Jason" not in block


def test_memory_injection_filters_ui_noise(app, test_user):
    with app.app_context():
        upsert_fact(
            test_user.id,
            scope="user",
            key="ui:noise",
            value="AI Cannot Access Desktop",
            source_conversation_id="c-noise",
            source_message_index=0,
            confidence=0.9,
        )
        block = build_memory_injection_block(test_user.id, "c-noise", "desktop")
    assert "AI Cannot Access Desktop" not in block


def test_initialize_chat_includes_user_memory_before_context(app, test_user):
    with app.test_request_context("/"):
        login_user(test_user)
        _, system_prompt, conversation, _ = initialize_chat({
            "conversation_id": "",
            "is_new_conversation": True,
            "messages": '[{"role":"user","content":"Do you know my name?"}]',
        })
    assert "=== USER MEMORY ===" in system_prompt
    assert f"username: {test_user.username}" in system_prompt
    assert "=== RELEVANT CONTEXT ONLY ===" in system_prompt
    assert system_prompt.index("=== USER MEMORY ===") < system_prompt.index("=== RELEVANT CONTEXT ONLY ===")
    assert conversation["id"]


def test_initialize_chat_ingests_identity_facts_from_user_messages(app, test_user):
    with app.test_request_context("/"):
        login_user(test_user)
        initialize_chat({
            "conversation_id": "",
            "is_new_conversation": True,
            "messages": '[{"role":"user","content":"My name is Morgan"},{"role":"assistant","content":"ok"},{"role":"user","content":"Do you know my name?"}]',
        })
    with app.app_context():
        user_facts = list_facts(test_user.id, scope="user")
    assert any(fact.get("key") == "identity:name" and fact.get("value") == "Morgan" for fact in user_facts)
