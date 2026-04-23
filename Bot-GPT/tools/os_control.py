import base64
import io
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

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


def move_mouse(x: int, y: int) -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    pyautogui.moveTo(int(x), int(y), duration=0.15)
    return {"status": "success", "action": "move_mouse", "x": int(x), "y": int(y)}


def click(button: str = "left") -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    btn = button if button in {"left", "right", "middle"} else "left"
    pyautogui.click(button=btn)
    return {"status": "success", "action": "click", "button": btn}


def type_text(text: str) -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    pyautogui.typewrite(str(text), interval=0.02)
    return {"status": "success", "action": "type_text", "length": len(str(text))}


def press_key(key: str) -> Dict[str, object]:
    error = _ensure_input_available()
    if error:
        return {"status": "error", "message": error}
    RATE_LIMITER.wait()
    pyautogui.press(str(key))
    return {"status": "success", "action": "press_key", "key": str(key)}


def open_app(name: str) -> Dict[str, object]:
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
        return {"status": "success", "action": "open_app", "name": app_name}
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
