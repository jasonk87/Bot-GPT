import hashlib
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None


def _load_image(path: str):
    if Image is None:
        raise RuntimeError("Pillow is unavailable")
    return Image.open(path)


def ocr_screen(image_path: Optional[str] = None, conversation_id=None, user_id=None, region: Optional[Tuple[int, int, int, int]] = None) -> Dict[str, object]:
    if not image_path:
        from tools.os_control import capture_screen

        shot = capture_screen(region=region, conversation_id=conversation_id, user_id=user_id)
        if shot.get("status") != "success":
            return {"status": "error", "message": shot.get("message", "capture failed")}
        image_path = shot.get("path")

    if pytesseract is None or Image is None:
        return {
            "status": "error",
            "message": "OCR dependencies unavailable",
            "image_path": image_path,
            "texts": [],
        }

    image = _load_image(image_path)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    texts: List[Dict[str, object]] = []
    for idx, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text or "").strip()
        if not text:
            continue
        conf = float(data.get("conf", [0])[idx]) if data.get("conf") else 0.0
        left = int(data.get("left", [0])[idx])
        top = int(data.get("top", [0])[idx])
        width = int(data.get("width", [0])[idx])
        height = int(data.get("height", [0])[idx])
        texts.append(
            {
                "text": text,
                "bbox": {"x": left, "y": top, "width": width, "height": height},
                "confidence": max(0.0, min(1.0, conf / 100.0)),
            }
        )

    return {
        "status": "success",
        "image_path": image_path,
        "texts": texts,
    }


def detect_ui_elements(ocr_result: Dict[str, object]) -> Dict[str, object]:
    tokens = ocr_result.get("texts", []) if isinstance(ocr_result, dict) else []
    elements = []

    for token in tokens:
        text = str(token.get("text") or "")
        bbox = token.get("bbox") or {}
        width = float(bbox.get("width") or 0)
        height = float(bbox.get("height") or 1)
        ratio = width / max(height, 1.0)

        kind = "label"
        lowered = text.lower()
        if any(k in lowered for k in ["ok", "submit", "save", "cancel", "next", "run"]):
            kind = "button"
        elif text.startswith("http") or "." in text and "/" in text:
            kind = "link"
        elif any(k in lowered for k in ["search", "email", "password", "username"]) and ratio > 2:
            kind = "text_field"
        elif any(k in lowered for k in ["menu", "file", "edit", "view"]):
            kind = "menu"
        elif any(k in lowered for k in ["dialog", "warning", "confirm"]):
            kind = "dialog"
        elif "[ ]" in text or "☐" in text:
            kind = "checkbox"

        confidence = float(token.get("confidence") or 0.0)
        confidence = max(confidence, 0.5 if kind != "label" else confidence)

        elements.append(
            {
                "element_type": kind,
                "text": text,
                "bbox": bbox,
                "confidence": min(1.0, confidence),
            }
        )

    return {
        "status": "success",
        "image_path": ocr_result.get("image_path") if isinstance(ocr_result, dict) else None,
        "elements": elements,
    }


def find_visual_target(
    *,
    anchor: Dict[str, object],
    ocr_result: Optional[Dict[str, object]] = None,
    ui_elements: Optional[Dict[str, object]] = None,
    min_confidence: float = 0.55,
    conversation_id=None,
    user_id=None,
) -> Dict[str, object]:
    if ocr_result is None:
        ocr_result = ocr_screen(conversation_id=conversation_id, user_id=user_id)
    if ocr_result.get("status") != "success":
        return {"status": "error", "message": "ocr_failed", "confidence": 0.0}

    if ui_elements is None:
        ui_elements = detect_ui_elements(ocr_result)

    anchor_text = str((anchor or {}).get("text") or "").lower().strip()
    anchor_type = str((anchor or {}).get("element_type") or "").strip()
    region = (anchor or {}).get("region") or {}

    best = None
    for element in ui_elements.get("elements", []):
        score = 0.0
        if anchor_text and anchor_text in str(element.get("text") or "").lower():
            score += 0.6
        if anchor_type and anchor_type == element.get("element_type"):
            score += 0.3
        bbox = element.get("bbox") or {}
        if region:
            within_x = float(region.get("x", -1e9)) <= float(bbox.get("x", 0)) <= float(region.get("x", 1e9)) + float(region.get("width", 1e9))
            within_y = float(region.get("y", -1e9)) <= float(bbox.get("y", 0)) <= float(region.get("y", 1e9)) + float(region.get("height", 1e9))
            if within_x and within_y:
                score += 0.1
        score += float(element.get("confidence") or 0.0) * 0.2

        if best is None or score > best[0]:
            best = (score, element)

    if best is None or best[0] < min_confidence:
        return {
            "status": "low_confidence",
            "confidence": 0.0 if best is None else best[0],
            "target": None,
            "should_abort": True,
        }

    target = best[1]
    bbox = target.get("bbox") or {}
    return {
        "status": "success",
        "confidence": best[0],
        "target": {
            "text": target.get("text"),
            "element_type": target.get("element_type"),
            "bbox": bbox,
            "x": int(float(bbox.get("x", 0)) + float(bbox.get("width", 0)) / 2),
            "y": int(float(bbox.get("y", 0)) + float(bbox.get("height", 0)) / 2),
        },
        "should_abort": False,
    }


def _state_hash(texts: List[Dict[str, object]]) -> str:
    serialized = "\n".join(sorted(str(item.get("text", "")) for item in texts))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_visual_state(
    *,
    rule: Dict[str, object],
    current_state: Dict[str, object],
    previous_state: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    rule = rule or {}
    texts = current_state.get("texts", [])
    elements = current_state.get("elements", [])

    if rule.get("expected_text"):
        expected = str(rule["expected_text"]).lower()
        matched = any(expected in str(t.get("text", "")).lower() for t in texts)
        return {"status": "success" if matched else "error", "matched": matched, "check": "expected_text"}

    if rule.get("element_exists"):
        spec = rule.get("element_exists") or {}
        t = str(spec.get("text") or "").lower()
        e_type = str(spec.get("element_type") or "")
        matched = any((not t or t in str(e.get("text", "")).lower()) and (not e_type or e_type == e.get("element_type")) for e in elements)
        return {"status": "success" if matched else "error", "matched": matched, "check": "element_exists"}

    if "dialog_present" in rule:
        present = any(e.get("element_type") == "dialog" for e in elements)
        matched = bool(rule.get("dialog_present")) == present
        return {"status": "success" if matched else "error", "matched": matched, "check": "dialog_present"}

    if rule.get("url_changed"):
        prev_url = (previous_state or {}).get("url")
        curr_url = current_state.get("url")
        matched = bool(prev_url) and bool(curr_url) and prev_url != curr_url
        return {"status": "success" if matched else "error", "matched": matched, "check": "url_changed"}

    if rule.get("ocr_text_changed"):
        prev_hash = _state_hash((previous_state or {}).get("texts", [])) if previous_state else None
        curr_hash = _state_hash(texts)
        matched = bool(prev_hash) and prev_hash != curr_hash
        return {"status": "success" if matched else "error", "matched": matched, "check": "ocr_text_changed"}

    if rule.get("region_changed"):
        prev_hash = (previous_state or {}).get("region_hash")
        curr_hash = current_state.get("region_hash")
        matched = bool(prev_hash) and bool(curr_hash) and prev_hash != curr_hash
        return {"status": "success" if matched else "error", "matched": matched, "check": "region_changed"}

    return {"status": "success", "matched": True, "check": "no_rule"}


def summarize_visual_state(current_state: Dict[str, object]) -> str:
    texts = [str(t.get("text")) for t in current_state.get("texts", [])[:8]]
    element_counts = {}
    for element in current_state.get("elements", []):
        kind = element.get("element_type", "unknown")
        element_counts[kind] = element_counts.get(kind, 0) + 1
    return f"Texts: {', '.join(texts)} | Elements: {element_counts}"
