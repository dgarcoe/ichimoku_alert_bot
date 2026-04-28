"""Helpers for parsing timeframe strings like '1h', '4h', '1d'."""

from __future__ import annotations

import re

_INTERVAL_RE = re.compile(r"^(\d+)([mhdw])$")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def interval_seconds(timeframe: str) -> int:
    """Return the number of seconds in one bar of `timeframe` (e.g. '4h' -> 14400)."""
    m = _INTERVAL_RE.match(timeframe)
    if not m:
        raise ValueError(f"Cannot parse timeframe: {timeframe}")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]
