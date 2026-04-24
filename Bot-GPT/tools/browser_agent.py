from typing import Dict, Optional

from flask import current_app

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None


_PLAYWRIGHT = None
_BROWSER = None
_PAGE = None


def _maybe_record_step(
    *,
    user_id: Optional[int],
    action_type: str,
    parameters: Dict[str, object],
    expected_text: str = "",
    fallback_hint: Optional[Dict[str, object]] = None,
    recording_session_id: Optional[str] = None,
):
    if user_id is None:
        return
    try:
        if not current_app.config.get("WORKFLOW_LEARNING_ENABLED", True):
            return
        from workflow_learning import record_workflow_step, start_recording_session

        session_id = recording_session_id or start_recording_session(
            current_app.instance_path,
            int(user_id),
            name="Auto-recorded browser workflow",
            description="Captured from successful browser actions",
        )
        record_workflow_step(
            current_app.instance_path,
            int(user_id),
            session_id,
            action_type=action_type,
            parameters=parameters,
            context={"what_changed": f"{action_type} executed"},
            verification_rule={"expected_text": expected_text} if expected_text else {},
            fallback_hints=[fallback_hint] if fallback_hint else [],
        )
    except Exception:
        return


def _ensure_page() -> Optional[str]:
    global _PLAYWRIGHT, _BROWSER, _PAGE
    if _PAGE is not None:
        return None
    if sync_playwright is None:
        return "Playwright is unavailable"
    try:
        _PLAYWRIGHT = sync_playwright().start()
        _BROWSER = _PLAYWRIGHT.chromium.launch(headless=True)
        context = _BROWSER.new_context()
        _PAGE = context.new_page()
        return None
    except Exception as exc:
        return f"Failed to start browser: {exc}"


def open_url(url: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    try:
        _PAGE.goto(str(url), wait_until="domcontentloaded", timeout=30000)
        payload = {"status": "success", "url": _PAGE.url}
        _maybe_record_step(user_id=user_id, action_type="open_url", parameters={"url": str(url)}, expected_text=expected_text, recording_session_id=recording_session_id)
        return payload
    except Exception as exc:
        return {"status": "error", "message": f"Navigation failed: {exc}"}


def find_element_by_text(text: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    locator = _PAGE.get_by_text(str(text), exact=False)
    count = locator.count()
    payload = {"status": "success", "text": str(text), "matches": int(count)}
    _maybe_record_step(user_id=user_id, action_type="find_element_by_text", parameters={"text": str(text)}, expected_text=expected_text or str(text), recording_session_id=recording_session_id)
    return payload


def click_element(text: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    locator = _PAGE.get_by_text(str(text), exact=False).first
    try:
        locator.click(timeout=5000)
        payload = {"status": "success", "clicked_text": str(text)}
        _maybe_record_step(
            user_id=user_id,
            action_type="click_element",
            parameters={"text": str(text)},
            expected_text=expected_text,
            fallback_hint={"action_type": "find_element_by_text", "parameters": {"text": str(text)}},
            recording_session_id=recording_session_id,
        )
        return payload
    except Exception as exc:
        return {"status": "error", "message": f"Click failed: {exc}"}


def extract_visible_text(max_chars: int = 2000) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    try:
        text = _PAGE.inner_text("body")
        return {"status": "success", "text": text[: int(max_chars)]}
    except Exception as exc:
        return {"status": "error", "message": f"Text extraction failed: {exc}"}
