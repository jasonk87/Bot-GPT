import tools.runtime as runtime
from tools import os_control
from tools import senses


class DummyImage:
    width = 100
    height = 80

    def save(self, path_or_buff, fmt=None, format=None):
        if hasattr(path_or_buff, "write"):
            path_or_buff.write(b"img")
            return
        with open(path_or_buff, "wb") as handle:
            handle.write(b"img")


class DummyGrabber:
    @staticmethod
    def grab(bbox=None):
        return DummyImage()


class DummyPyAuto:
    def __init__(self):
        self.calls = []

    def moveTo(self, x, y, duration=0):
        self.calls.append(("move", x, y))

    def click(self, button="left"):
        self.calls.append(("click", button))

    def typewrite(self, text, interval=0):
        self.calls.append(("type", text))

    def press(self, key):
        self.calls.append(("press", key))


class DummyPage:
    url = "https://example.com"

    def goto(self, *_args, **_kwargs):
        return None

    def get_by_text(self, text, exact=False):
        class Locator:
            def count(self_inner):
                return 1

            @property
            def first(self_inner):
                return self_inner

            def click(self_inner, timeout=0):
                return None

        return Locator()

    def inner_text(self, _selector):
        return "Dashboard complete"


def test_capture_screen_and_input_actions(monkeypatch):
    monkeypatch.setattr(os_control, "ImageGrab", DummyGrabber)
    dummy_input = DummyPyAuto()
    monkeypatch.setattr(os_control, "pyautogui", dummy_input)

    shot = os_control.capture_screen(conversation_id="c1", user_id=1)
    assert shot["status"] == "success"
    assert shot["width"] == 100

    assert os_control.move_mouse(10, 12)["status"] == "success"
    assert os_control.click("left")["status"] == "success"
    assert os_control.type_text("hello")["status"] == "success"
    assert os_control.press_key("enter")["status"] == "success"


def test_browser_and_visual_feedback(monkeypatch):
    import tools.browser_agent as browser_agent

    monkeypatch.setattr(browser_agent, "_PAGE", DummyPage())

    assert browser_agent.open_url("https://example.com")["status"] == "success"
    assert browser_agent.find_element_by_text("Dashboard")["matches"] == 1
    assert browser_agent.click_element("Dashboard")["status"] == "success"
    assert "Dashboard" in browser_agent.extract_visible_text()["text"]

    monkeypatch.setattr(senses, "ocr_screen", lambda **kwargs: {"status": "success", "image_path": "/tmp/a.png", "texts": [{"text": "expected signal"}]})
    monkeypatch.setattr(senses, "detect_ui_elements", lambda ocr_result: {"status": "success", "elements": [{"element_type": "button", "text": "expected"}]})
    monkeypatch.setattr(senses, "verify_visual_state", lambda rule, current_state: {"status": "success", "matched": True})

    feedback = senses.visual_feedback_step(expected_text="signal")
    assert feedback["status"] == "success"
    assert feedback["verification"]["matched"] is True


def test_runtime_registry_contains_os_agent_tools():
    expected = {
        "capture_screen",
        "move_mouse",
        "click",
        "type_text",
        "press_key",
        "open_app",
        "focus_window",
        "close_window",
        "open_url",
        "find_element_by_text",
        "click_element",
        "extract_visible_text",
        "visual_feedback_step",
        "ocr_screen",
        "detect_ui_elements",
        "find_visual_target",
        "verify_visual_state",
    }
    assert expected.issubset(set(runtime.TOOL_REGISTRY.keys()))
