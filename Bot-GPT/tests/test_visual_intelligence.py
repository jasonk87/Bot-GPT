from types import SimpleNamespace

import visual_intelligence as vi
from workflow_learning import (
    finalize_recording_session,
    record_workflow_step,
    replay_workflow,
    start_recording_session,
)


class DummyImage:
    pass


def test_ocr_result_normalization(monkeypatch, tmp_path):
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"img")

    monkeypatch.setattr(vi, "Image", SimpleNamespace(open=lambda path: DummyImage()))
    monkeypatch.setattr(
        vi,
        "pytesseract",
        SimpleNamespace(
            Output=SimpleNamespace(DICT="dict"),
            image_to_data=lambda image, output_type=None: {
                "text": ["Run", "", "Button"],
                "conf": [95, 0, 88],
                "left": [10, 0, 40],
                "top": [20, 0, 20],
                "width": [25, 0, 60],
                "height": [18, 0, 20],
            },
        ),
    )

    result = vi.ocr_screen(image_path=str(image_path))
    assert result["status"] == "success"
    assert len(result["texts"]) == 2
    assert result["texts"][0]["bbox"]["x"] == 10


def test_ui_element_detection_from_ocr_tokens():
    ocr_result = {
        "status": "success",
        "image_path": "/tmp/a.png",
        "texts": [
            {"text": "Submit", "bbox": {"x": 10, "y": 20, "width": 70, "height": 18}, "confidence": 0.9},
            {"text": "search", "bbox": {"x": 10, "y": 50, "width": 140, "height": 20}, "confidence": 0.8},
            {"text": "menu", "bbox": {"x": 10, "y": 80, "width": 60, "height": 20}, "confidence": 0.7},
        ],
    }
    detected = vi.detect_ui_elements(ocr_result)
    kinds = {e["element_type"] for e in detected["elements"]}
    assert "button" in kinds
    assert "text_field" in kinds
    assert "menu" in kinds


def test_visual_anchor_matching_and_low_confidence():
    ocr_result = {
        "status": "success",
        "texts": [{"text": "Run job", "bbox": {"x": 5, "y": 5, "width": 80, "height": 20}, "confidence": 0.95}],
    }
    elements = {
        "status": "success",
        "elements": [{"text": "Run job", "element_type": "button", "bbox": {"x": 5, "y": 5, "width": 80, "height": 20}, "confidence": 0.9}],
    }
    hit = vi.find_visual_target(anchor={"text": "Run", "element_type": "button"}, ocr_result=ocr_result, ui_elements=elements)
    assert hit["status"] == "success"
    assert hit["target"]["x"] > 0

    miss = vi.find_visual_target(anchor={"text": "Unknown"}, ocr_result=ocr_result, ui_elements=elements, min_confidence=0.9)
    assert miss["status"] == "low_confidence"
    assert miss["should_abort"] is True


def test_visual_verification_rules():
    state = {
        "texts": [{"text": "Settings"}],
        "elements": [{"element_type": "dialog", "text": "Confirm"}],
        "url": "https://x/new",
    }
    prev = {"texts": [{"text": "Home"}], "elements": [], "url": "https://x/old"}

    assert vi.verify_visual_state(rule={"expected_text": "settings"}, current_state=state)["status"] == "success"
    assert vi.verify_visual_state(rule={"element_exists": {"element_type": "dialog"}}, current_state=state)["status"] == "success"
    assert vi.verify_visual_state(rule={"dialog_present": True}, current_state=state)["status"] == "success"
    assert vi.verify_visual_state(rule={"url_changed": True}, current_state=state, previous_state=prev)["status"] == "success"
    assert vi.verify_visual_state(rule={"ocr_text_changed": True}, current_state=state, previous_state=prev)["status"] == "success"


def test_workflow_replay_blocks_low_confidence_targets(app):
    session = start_recording_session(app.instance_path, 1, name="Anchored flow")
    record_workflow_step(
        app.instance_path,
        1,
        session,
        action_type="click",
        parameters={"button": "left"},
        verification_rule={"expected_text": "Done"},
        visual_anchor={"text": "Very Specific Missing Anchor", "element_type": "button"},
    )
    record_workflow_step(app.instance_path, 1, session, action_type="type_text", parameters={"text": "hello"})
    wf = finalize_recording_session(app.instance_path, 1, session, successful=True, min_steps_to_record=2)

    result = replay_workflow(
        app.instance_path,
        1,
        wf["workflow_id"],
        executors={"click": lambda **kwargs: {"status": "success"}, "type_text": lambda **kwargs: {"status": "success"}},
        verifier=lambda: {"texts": [{"text": "No match here"}], "elements": []},
    )
    assert result["status"] == "error"
    assert any("Low-confidence" in r.get("message", "") for r in result["results"])
