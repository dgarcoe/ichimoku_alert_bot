"""
Tracks which signals have already been notified so we don't spam on every
poll. Persists a small JSON file so restarts don't resend old alerts.

Key format: "{source}:{symbol}:{timeframe}:{bar_time_iso}:{side}"
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Set

log = logging.getLogger(__name__)


class SeenStore:
    def __init__(self, path: str, max_entries: int = 5000):
        self._path = path
        self._max = max_entries
        self._lock = threading.Lock()
        self._seen: Set[str] = set()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._seen = set(data[-self._max:])
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read seen-state at %s: %s", self._path, exc)

    def _save_unlocked(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            # Keep only the most recent entries bounded.
            trimmed = list(self._seen)[-self._max:]
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(trimmed, f)
            os.replace(tmp, self._path)
        except OSError as exc:
            log.warning("Could not persist seen-state: %s", exc)

    def contains(self, key: str) -> bool:
        with self._lock:
            return key in self._seen

    def add(self, key: str) -> None:
        with self._lock:
            self._seen.add(key)
            self._save_unlocked()
