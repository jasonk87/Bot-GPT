import base64
import io
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from flask import current_app

try:
    import pyautogui
except Exception:  # pragma: no cover
    pyautogui = None

try:
    import pygetwindow
except Exception:  # pragma: no cover
    pygetwindow = None

try:
    from PIL import ImageGrab
except Exception:  # pragma: no cover
    ImageGrab = None


@dataclass
class _RateLimiter:
    min_interval: float = 0.2
    last_action_at: float = 0.0

    def wait(self):
        now = time.time()
        delta = now - self.last_action_at
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self.last_action_at = time.time()


RATE_LIMITER = _RateLimiter()


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
            name="Auto-recorded OS workflow",
            description="Captured from successful OS/browser actions",
        )
        anchor = {}
        anchor_text = parameters.get("target_text") or expected_text
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


def _screenshot_dir(conversation_id=None, user_id=None) -> str:
    base = os.path.join("/tmp", "botgpt_os_agent")
    if user_id is not None:
        base = os.path.join(base, str(user_id))
    if conversation_id is not None:
        base = os.path.join(base, str(conversation_id))
    os.makedirs(base, exist_ok=True)
    return base


def capture_screen(region: Optional[Tuple[int, int, int, int]] = None, conversation_id=None, user_id=None) -> Dict[str, object]:
    if ImageGrab is None:
        return {"status": "error", "message": "Screen capture dependency unavailable"}

    try:
        bbox = None
        if region:
            x, y, width, height = region
            bbox = (x, y, x + width, y + height)
        image = ImageGrab.grab(bbox=bbox)
        ts = int(time.time() * 1000)
        path = os.path.join(_screenshot_dir(conversation_id, user_id), f"screenshot_{ts}.png")
        image.save(path, "PNG")

        buff = io.BytesIO()
        image.save(buff, format="PNG")
        encoded = base64.b64encode(buff.getvalue()).decode("utf-8")
        return {
            "status": "success",
            "path": path,
            "encoding": "base64",
            "image_base64": encoded,
            "width": image.width,
            "height": image.height,
            "region": region,
        }
    except Exception as exc:
        return {"status": "error", "message": f"Screenshot failed: {exc}"}


def _ensure_input_available() -> Optional[str]:
    if pyautogui is None:
        return "Input automation dependency unavailable"
    return None


def move_mouse(x: int, y: int, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    pyautogui.moveTo(int(x), int(y), duration=0.15)
    payload = {"status": "success", "action": "move_mouse", "x": int(x), "y": int(y)}
    _maybe_record_step(user_id=user_id, action_type="move_mouse", parameters={"x": int(x), "y": int(y)}, expected_text=expected_text, recording_session_id=recording_session_id)
    return payload


def click(button: str = "left", user_id: Optional[int] = None, expected_text: str = "", target_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    btn = button if button in {"left", "right", "middle"} else "left"
    pyautogui.click(button=btn)
    payload = {"status": "success", "action": "click", "button": btn}
    _maybe_record_step(
        user_id=user_id,
        action_type="click",
        parameters={"button": btn, "target_text": target_text},
        expected_text=expected_text,
        fallback_hint={"action_type": "click_element", "parameters": {"text": target_text}} if target_text else None,
        recording_session_id=recording_session_id,
    )
    return payload


def type_text(text: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    pyautogui.typewrite(str(text), interval=0.02)
    payload = {"status": "success", "action": "type_text", "length": len(str(text))}
    _maybe_record_step(user_id=user_id, action_type="type_text", parameters={"text": str(text)}, expected_text=expected_text or str(text), recording_session_id=recording_session_id)
    return payload


def press_key(key: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    pyautogui.press(str(key))
    payload = {"status": "success", "action": "press_key", "key": str(key)}
    _maybe_record_step(user_id=user_id, action_type="press_key", parameters={"key": str(key)}, expected_text=expected_text, recording_session_id=recording_session_id)
    return payload


def open_app(name: str, user_id: Optional[int] = None, expected_text: str = "", recording_session_id: Optional[str] = None) -> Dict[str, object]:
    RATE_LIMITER.wait()
    app_name = str(name).strip()
    if not app_name:
        return {"status": "error", "message": "App name is required"}
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "", app_name], shell=False)
        elif os.name == "posix":
            subprocess.Popen([app_name])
        else:
            return {"status": "error", "message": "Unsupported OS for open_app"}
        payload = {"status": "success", "action": "open_app", "name": app_name}
        _maybe_record_step(user_id=user_id, action_type="open_app", parameters={"name": app_name}, expected_text=expected_text, recording_session_id=recording_session_id)
        return payload
    except Exception as exc:
        return {"status": "error", "message": f"Failed to open app: {exc}"}


def focus_window(title: str) -> Dict[str, object]:
    if pygetwindow is None:
        return {"status": "error", "message": "Window control dependency unavailable"}
    target = str(title).strip().lower()
    for win in pygetwindow.getAllTitles():
        if target and target in win.lower():
            window = pygetwindow.getWindowsWithTitle(win)[0]
            window.activate()
            return {"status": "success", "action": "focus_window", "title": win}
    return {"status": "error", "message": "Window not found"}


def close_window(title: str) -> Dict[str, object]:
    if pygetwindow is None:
        return {"status": "error", "message": "Window control dependency unavailable"}
    target = str(title).strip().lower()
    for win in pygetwindow.getAllTitles():
        if target and target in win.lower():
            window = pygetwindow.getWindowsWithTitle(win)[0]
            window.close()
            return {"status": "success", "action": "close_window", "title": win}
    return {"status": "error", "message": "Window not found"}
