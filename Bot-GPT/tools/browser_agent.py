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
        from visual_intelligence import ocr_screen, detect_ui_elements, find_visual_target

        session_id = recording_session_id or start_recording_session(
            current_app.instance_path,
            int(user_id),
            name="Auto-recorded browser workflow",
            description="Captured from successful browser actions",
        )
        anchor = {}
        anchor_text = parameters.get("text") or expected_text
        if anchor_text:
            ocr_result = ocr_screen(user_id=user_id)
            if ocr_result.get("status") == "success":
                elements = detect_ui_elements(ocr_result)
                target = find_visual_target(
                    anchor={"text": str(anchor_text)},
                    ocr_result=ocr_result,
                    ui_elements=elements,
                    min_confidence=0.4,
                )
                if target.get("status") == "success":
                    anchor = {
                        "text": target["target"].get("text"),
                        "element_type": target["target"].get("element_type"),
                        "region": target["target"].get("bbox"),
                    }

        record_workflow_step(
            current_app.instance_path,
            int(user_id),
            session_id,
            action_type=action_type,
            parameters=parameters,
            context={"what_changed": f"{action_type} executed"},
            verification_rule={"expected_text": expected_text} if expected_text else {},
            fallback_hints=[fallback_hint] if fallback_hint else [],
            visual_anchor=anchor,
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


def fill_input(label: str, value: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    try:
        locator = _PAGE.get_by_label(str(label), exact=False).first
        if locator.count() == 0:
            locator = _PAGE.get_by_placeholder(str(label), exact=False).first
        locator.fill(str(value), timeout=5000)
        payload = {"status": "success", "filled_label": str(label), "value": str(value)}
        _maybe_record_step(
            user_id=user_id,
            action_type="fill_input",
            parameters={"label": str(label), "value": str(value)},
            expected_text=expected_text,
            recording_session_id=recording_session_id,
        )
        return payload
    except Exception as exc:
        return {"status": "error", "message": f"Fill failed: {exc}"}


def press_key_browser(key: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    try:
        _PAGE.keyboard.press(str(key))
        payload = {"status": "success", "pressed_key": str(key)}
        _maybe_record_step(
            user_id=user_id,
            action_type="press_key_browser",
            parameters={"key": str(key)},
            expected_text=expected_text,
            recording_session_id=recording_session_id,
        )
        return payload
    except Exception as exc:
        return {"status": "error", "message": f"Key press failed: {exc}"}


def take_browser_screenshot() -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    try:
        import base64
        screenshot_bytes = _PAGE.screenshot()
        b64_img = base64.b64encode(screenshot_bytes).decode("utf-8")
        return {"status": "success", "image_base64": b64_img}
    except Exception as exc:
        return {"status": "error", "message": f"Screenshot failed: {exc}"}


def extract_visible_text(max_chars: int = 2000) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    try:
        # Instead of just inner_text, grab a simplified structural view
        # We'll evaluate a script to return elements with their roles and text
        js_extractor = """
            () => {
                const elements = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
                    acceptNode: function(node) {
                        const tag = node.tagName.toLowerCase();
                        if (['script', 'style', 'noscript', 'meta'].includes(tag)) return NodeFilter.FILTER_REJECT;
                        if (node.offsetParent === null) return NodeFilter.FILTER_REJECT; // hidden
                        if (['a', 'button', 'input', 'select', 'textarea', 'h1', 'h2', 'h3', 'p'].includes(tag)) {
                            return NodeFilter.FILTER_ACCEPT;
                        }
                        return NodeFilter.FILTER_SKIP;
                    }
                });

                let node;
                while ((node = walker.nextNode())) {
                    const tag = node.tagName.toLowerCase();
                    let text = node.innerText || node.value || node.placeholder || '';
                    text = text.trim();
                    if (text) {
                        let role = tag;
                        if (tag === 'input') {
                            role = `input[${node.type}]`;
                        }
                        elements.push(`[${role}] ${text}`);
                    }
                }
                return elements.join('\\n');
            }
        """
        structural_text = _PAGE.evaluate(js_extractor)
        if not structural_text:
            structural_text = _PAGE.inner_text("body")

        return {"status": "success", "text": structural_text[: int(max_chars)]}
    except Exception as exc:
        return {"status": "error", "message": f"Text extraction failed: {exc}"}
