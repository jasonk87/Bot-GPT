from typing import Dict, Optional

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None


_PLAYWRIGHT = None
_BROWSER = None
_PAGE = None


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


def open_url(url: str) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    try:
        _PAGE.goto(str(url), wait_until="domcontentloaded", timeout=30000)
        return {"status": "success", "url": _PAGE.url}
    except Exception as exc:
        return {"status": "error", "message": f"Navigation failed: {exc}"}


def find_element_by_text(text: str) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    locator = _PAGE.get_by_text(str(text), exact=False)
    count = locator.count()
    return {"status": "success", "text": str(text), "matches": int(count)}


def click_element(text: str) -> Dict[str, object]:
    error = _ensure_page()
    if error:
        return {"status": "error", "message": error}
    locator = _PAGE.get_by_text(str(text), exact=False).first
    try:
        locator.click(timeout=5000)
        return {"status": "success", "clicked_text": str(text)}
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
