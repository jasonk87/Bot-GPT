from typing import Dict, Optional, Tuple

from .browser_agent import extract_visible_text
from .os_control import capture_screen as os_capture_screen


def capture_screen(conversation_id=None, user_id=None, region: Optional[Tuple[int, int, int, int]] = None):
    """Capture a screenshot for the current desktop or a region.

    region: (x, y, width, height)
    """
    return os_capture_screen(region=region, conversation_id=conversation_id, user_id=user_id)


def visual_feedback_step(expected_text: str = "", conversation_id=None, user_id=None) -> Dict[str, object]:
    """Observe current UI and verify expected text heuristically."""
    screenshot = capture_screen(conversation_id=conversation_id, user_id=user_id)
    if screenshot.get("status") != "success":
        return {"status": "error", "message": screenshot.get("message", "capture failed")}

    text_result = extract_visible_text(max_chars=5000)
    visible_text = text_result.get("text", "") if text_result.get("status") == "success" else ""
    matched = bool(expected_text and expected_text.lower() in visible_text.lower())

    return {
        "status": "success",
        "screenshot": {
            "path": screenshot.get("path"),
            "width": screenshot.get("width"),
            "height": screenshot.get("height"),
        },
        "verification": {
            "expected_text": expected_text,
            "matched": matched,
            "observed_text_excerpt": visible_text[:300],
        },
    }
