"""Configuration loader."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand_env(value):
    """Expand ${VAR} and ${VAR:-default} inside string values, recursively."""
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2) or ""
            return os.environ.get(var_name, default)
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


@dataclass
class SymbolConfig:
    symbol: str
    source: str            # "binance" or "yahoo"
    timeframe: str         # "1h", "4h", "1d", ...
    label: Optional[str] = None

    @property
    def display(self) -> str:
        return self.label or self.symbol


@dataclass
class AppConfig:
    telegram_bot_token: str
    telegram_chat_ids: List[str]
    poll_interval_seconds: int
    ichimoku_tenkan: int
    ichimoku_kijun: int
    ichimoku_senkou_b: int
    ichimoku_displacement: int
    cross_lookback_bars: int
    history_bars: int
    # Drop signals whose bar closed more than this many seconds ago. This
    # prevents alerting on stale signals after a (re)start, where the bot
    # would otherwise notify for a bar that closed hours earlier.
    max_signal_age_seconds: int
    symbols: List[SymbolConfig] = field(default_factory=list)
    state_path: str = "/data/seen_signals.json"
    startup_message: bool = True


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw = _expand_env(raw)

    tg = raw.get("telegram", {})
    ichimoku = raw.get("ichimoku", {})
    scan = raw.get("scan", {})

    chat_ids_raw = tg.get("chat_ids", [])
    if isinstance(chat_ids_raw, str):
        chat_ids = [c.strip() for c in chat_ids_raw.split(",") if c.strip()]
    else:
        chat_ids = [str(c) for c in chat_ids_raw]

    symbols = [
        SymbolConfig(
            symbol=item["symbol"],
            source=item["source"],
            timeframe=item["timeframe"],
            label=item.get("label"),
        )
        for item in raw.get("symbols", [])
    ]

    poll_interval_seconds = int(scan.get("poll_interval_seconds", 300))
    max_age = scan.get("max_signal_age_seconds")
    max_signal_age_seconds = (
        int(max_age) if max_age is not None else 2 * poll_interval_seconds
    )

    return AppConfig(
        telegram_bot_token=tg.get("bot_token", "") or "",
        telegram_chat_ids=chat_ids,
        poll_interval_seconds=poll_interval_seconds,
        ichimoku_tenkan=int(ichimoku.get("tenkan", 9)),
        ichimoku_kijun=int(ichimoku.get("kijun", 26)),
        ichimoku_senkou_b=int(ichimoku.get("senkou_b", 52)),
        ichimoku_displacement=int(ichimoku.get("displacement", 26)),
        cross_lookback_bars=int(scan.get("cross_lookback_bars", 60)),
        history_bars=int(scan.get("history_bars", 200)),
        max_signal_age_seconds=max_signal_age_seconds,
        symbols=symbols,
        state_path=raw.get("state_path", "/data/seen_signals.json"),
        startup_message=bool(raw.get("startup_message", True)),
    )
