import os
from flask import current_app


def get_users_path() -> str:
    """Single source of truth for users storage."""
    return os.path.join(current_app.instance_path, "users.json")


def get_conversation_index_path() -> str:
    return os.path.join(current_app.instance_path, "conversation_index.json")


def get_user_conversation_index_path() -> str:
    return os.path.join(current_app.instance_path, "user_conversation_index.json")


def get_conversation_path(owner_id, conversation_id) -> str:
    return os.path.join(
        current_app.instance_path,
        str(owner_id),
        "conversations",
        f"{conversation_id}.json",
    )


def migrate_legacy_users_file(app):
    """Migrate legacy USER_DATA_DIR/users.json into instance/users.json when needed."""
    instance_users = os.path.join(app.instance_path, "users.json")
    legacy_dir = app.config.get("USER_DATA_DIR")
    legacy_users = os.path.join(legacy_dir, "users.json") if legacy_dir else None

    if not legacy_users or not os.path.exists(legacy_users):
        return

    if os.path.exists(instance_users):
        app.logger.info("users migration skipped; instance users.json already present")
        return

    os.makedirs(app.instance_path, exist_ok=True)
    with open(legacy_users, "r", encoding="utf-8") as src, open(instance_users, "w", encoding="utf-8") as dst:
        dst.write(src.read())

    app.logger.warning("migrated legacy users.json from USER_DATA_DIR to instance_path")
