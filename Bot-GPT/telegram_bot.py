import threading
from typing import Dict, Optional

import requests

from telegram_router import handle_telegram_command


class TelegramBotBridge:
    def __init__(self, app, *, token: str, poll_interval: float = 2.0):
        self.app = app
        self.token = token
        self.poll_interval = max(0.5, float(poll_interval))
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_update_id: Optional[int] = None

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def start(self) -> None:
        if not self.token or self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="telegram-bot-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run_loop(self):
        with self.app.app_context():
            while not self._stop_event.is_set():
                try:
                    updates = self._get_updates()
                    for update in updates:
                        self._handle_update(update)
                except Exception as exc:
                    self.app.logger.warning("Telegram polling error: %s", exc)
                self._stop_event.wait(self.poll_interval)

    def _api_request(self, method: str, payload: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        response = requests.post(
            f"{self.base_url}/{method}",
            json=payload or {},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def _get_updates(self):
        payload = {
            "timeout": 0,
            "allowed_updates": ["message"],
        }
        if self._last_update_id is not None:
            payload["offset"] = self._last_update_id + 1
        result = self._api_request("getUpdates", payload)
        updates = result.get("result", []) if isinstance(result, dict) else []
        return updates

    def _handle_update(self, update: Dict[str, object]) -> None:
        if not isinstance(update, dict):
            return

        update_id = update.get("update_id")
        if isinstance(update_id, int):
            self._last_update_id = update_id

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        text = str(message.get("text") or "").strip()
        chat_id = chat.get("id")
        if not text or chat_id is None:
            return

        response_text = handle_telegram_command(
            self.app,
            telegram_user_id=int(from_user.get("id") or chat_id),
            telegram_username=from_user.get("username"),
            text=text,
        )
        self.send_message(int(chat_id), response_text)

    def send_message(self, chat_id: int, text: str) -> None:
        if not text:
            return
        payload = {
            "chat_id": int(chat_id),
            "text": text[:3900],
        }
        try:
            self._api_request("sendMessage", payload)
        except Exception as exc:
            self.app.logger.warning("Telegram send failed: %s", exc)
