from __future__ import annotations

from typing import Iterable


def _normalize_admin_ids(raw_ids: Iterable) -> set[int]:
    normalized: set[int] = set()
    for value in raw_ids or []:
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_admin_usernames(raw_usernames: Iterable) -> set[str]:
    normalized: set[str] = set()
    for value in raw_usernames or []:
        if value is None:
            continue
        username = str(value).strip().lower()
        if username:
            normalized.add(username)
    return normalized


def is_admin_user(user, app_config) -> bool:
    if not user:
        return False

    admin_ids = _normalize_admin_ids(app_config.get("ADMIN_USER_IDS") or [])
    user_id = int(getattr(user, "id", -1))
    if user_id in admin_ids:
        return True

    admin_usernames = _normalize_admin_usernames(app_config.get("ADMIN_USERNAMES") or [])
    username = str(getattr(user, "username", "") or "").strip().lower()
    is_admin_by_username = bool(username and username in admin_usernames)
    if is_admin_by_username and user_id > 0:
        # Optional repair helper: promote known admin usernames into in-memory ID list
        # so legacy ID-only checks in dependent code paths stay compatible.
        _remember_admin_id(user_id, app_config)
    return is_admin_by_username


def _remember_admin_id(user_id: int, app_config) -> None:
    current_ids = _normalize_admin_ids(app_config.get("ADMIN_USER_IDS") or [])
    if user_id in current_ids:
        return
    current_ids.add(user_id)
    app_config["ADMIN_USER_IDS"] = sorted(current_ids)
