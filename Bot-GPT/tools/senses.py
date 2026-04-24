from typing import Dict, Optional, Tuple

from .os_control import capture_screen as os_capture_screen
from visual_intelligence import ocr_screen, detect_ui_elements, verify_visual_state


def capture_screen(conversation_id=None, user_id=None, region: Optional[Tuple[int, int, int, int]] = None):
    """Capture a screenshot for the current desktop or a region.

    region: (x, y, width, height)
    """
    return os_capture_screen(region=region, conversation_id=conversation_id, user_id=user_id)


def visual_feedback_step(expected_text: str = "", conversation_id=None, user_id=None) -> Dict[str, object]:
    """Observe current UI and verify expected text heuristically."""
    ocr_result = ocr_screen(conversation_id=conversation_id, user_id=user_id)
    if ocr_result.get("status") != "success":
        return {"status": "error", "message": ocr_result.get("message", "ocr failed")}
    ui_elements = detect_ui_elements(ocr_result)
    state = {
        "image_path": ocr_result.get("image_path"),
        "texts": ocr_result.get("texts", []),
        "elements": ui_elements.get("elements", []),
    }
    verification = verify_visual_state(
        rule={"expected_text": expected_text} if expected_text else {},
        current_state=state,
    )

    return {
        "status": "success" if verification.get("status") == "success" else "error",
        "screenshot": {
            "path": ocr_result.get("image_path"),
        },
        "verification": dict(verification, expected_text=expected_text),
        "state": state,
    }
