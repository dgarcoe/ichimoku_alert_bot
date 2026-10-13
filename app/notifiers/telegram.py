"""
Telegram bot notifier.

Uses the Bot API directly via HTTPS. Docs: https://core.telegram.org/bots/api
We only need sendMessage + getUpdates (the latter is optional, for /start).
"""

from __future__ import annotations

import logging
from typing import Iterable

import httpx

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_ids: Iterable[str],
        parse_mode: str = "HTML",
        timeout: float = 15.0,
    ):
        if not bot_token:
            raise ValueError("Telegram bot token is required.")
        self._token = bot_token
        self._chat_ids = [str(c) for c in chat_ids if str(c).strip()]
        self._parse_mode = parse_mode
        self._timeout = timeout
        self._base = f"https://api.telegram.org/bot{bot_token}"

    @property
    def chat_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self._chat_ids))

    def send(self, text: str, chat_ids=None) -> set[str]:
        if not self._chat_ids:
            log.warning("No chat IDs configured; dropping message.")
            return set()
        delivered = set()
        with httpx.Client(timeout=self._timeout) as client:
            for chat_id in (self.chat_ids if chat_ids is None else chat_ids):
                try:
                    resp = client.post(
                        f"{self._base}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": self._parse_mode,
                            "disable_web_page_preview": True,
                        },
                    )
                    # Never log response bodies or HTTP exception URLs: they may
                    # contain the bot token or user content.
                    if resp.status_code == 200 and resp.json().get("ok") is True:
                        delivered.add(chat_id)
                    else:
                        log.warning("Telegram delivery failed: HTTP %s", resp.status_code)
                except (httpx.HTTPError, ValueError):
                    log.warning("Telegram delivery failed: transport or invalid response")
        return delivered
