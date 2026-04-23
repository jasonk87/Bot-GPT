import json
import time
from flask import current_app
from flask_login import current_user

from models import (
    load_conversation,
    save_conversation,
    add_to_conversation_index,
    add_user_to_conversation_index,
    find_conversation_owner,
    check_permission,
)
from prompts import PERSONAS, DEFAULT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT
from shared_paths import (
    get_conversation_path,
    get_conversation_index_path,
    get_user_conversation_index_path,
)


def initialize_chat(data):
    conversation_id = data.get("conversation_id")
    index_path = get_conversation_index_path()
    conversation = None
    conversation_path = None

    if conversation_id and not data.get("is_new_conversation"):
        owner_id = find_conversation_owner(index_path, conversation_id)
        if not owner_id:
            raise ValueError("Conversation not found.")
        conversation_path = get_conversation_path(owner_id, conversation_id)
        conversation = load_conversation(conversation_path)
        if not conversation or not check_permission(conversation, current_user):
            raise ValueError("Conversation not found or you don't have access.")
    else:
        if not conversation_id:
            conversation_id = str(int(time.time() * 1000))
        owner_id = current_user.id
        conversation_path = get_conversation_path(owner_id, conversation_id)
        conversation = {
            "id": conversation_id,
            "title": "New Chat",
            "owner_id": owner_id,
            "project_id": data.get("project_id"),
            "participants": [{"user_id": owner_id, "role": "owner"}],
            "messages": [],
            "artifacts": [],
            "last_active_artifact_id": None,
            "created_at": time.time(),
        }
        save_conversation(conversation_path, conversation)
        add_to_conversation_index(index_path, conversation_id, owner_id)
        add_user_to_conversation_index(get_user_conversation_index_path(), owner_id, conversation_id)

    model = data.get("model") or current_user.selected_model
    persona_key = current_user.selected_persona or "default"
    system_prompt = PERSONAS.get(persona_key, {}).get("prompt", DEFAULT_SYSTEM_PROMPT)
    if data.get("agent_mode", False):
        system_prompt = AGENT_SYSTEM_PROMPT

    try:
        from memory import MemoryManager

        memory = MemoryManager(user_id=current_user.id)
        if conversation:
            memory.set_project_memory_file(
                conversation["owner_id"],
                conversation["id"],
                project_id=conversation.get("project_id"),
            )

        latest_query = None
        messages_raw = data.get("messages")
        if messages_raw:
            try:
                msgs = json.loads(messages_raw)
                if msgs and msgs[-1].get("role") == "user":
                    latest_query = msgs[-1].get("content")
            except Exception:
                pass

        memory_context = memory.get_all_context(query=latest_query)
        if memory_context:
            system_prompt += f"\n\n=== RECALLED MEMORY ===\n{memory_context}\n=======================\n"
    except Exception as e:
        current_app.logger.warning(f"Error injecting memory: {e}")

    return model, system_prompt, conversation, conversation_path
