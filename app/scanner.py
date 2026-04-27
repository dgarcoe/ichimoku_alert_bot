"""Scanner: fetch data, compute Ichimoku, detect signals, notify."""

from __future__ import annotations

import logging
from html import escape
from typing import Dict

from .config import AppConfig, SymbolConfig
from .data_sources import BinanceSource, DataSource, YahooSource
from .notifiers import TelegramNotifier
from .state import SeenStore
from .strategies import Signal, compute_ichimoku, detect_signal

log = logging.getLogger(__name__)


def build_sources(cfg: AppConfig) -> Dict[str, DataSource]:
    return {
        "binance": BinanceSource(),
        "yahoo": YahooSource(),
    }


def format_signal_message(sym: SymbolConfig, signal: Signal) -> str:
    arrow = "🟢 LONG" if signal.side == "long" else "🔴 SHORT"
    rr_risk = abs(signal.entry_price - signal.stop_loss)
    risk_pct = (rr_risk / signal.entry_price) * 100 if signal.entry_price else 0.0

    parts = [
        f"<b>{arrow} — {escape(sym.display)}</b>",
        f"<i>Ichimoku Chikou Breakout (post T/K cross)</i>",
        "",
        f"• Timeframe: <code>{escape(sym.timeframe)}</code>",
        f"• Source: <code>{escape(sym.source)}</code>",
        f"• Bar: <code>{escape(signal.bar_time.isoformat())}</code>",
        f"• Entry: <code>{signal.entry_price:g}</code>",
        f"• Stop:  <code>{signal.stop_loss:g}</code>  (risk ≈ {risk_pct:.2f}%)",
        f"• Tenkan: <code>{signal.tenkan:g}</code>  |  Kijun: <code>{signal.kijun:g}</code>",
        f"• Kumo: <code>{signal.kumo_bottom:g}</code> → <code>{signal.kumo_top:g}</code>",
        f"• Qualifying T/K cross: <code>{escape(signal.cross_bar_time.isoformat())}</code>",
        "",
        "<i>Targets: next S/R or opposite side of higher-TF Kumo. "
        "Trail with Kijun-sen.</i>",
    ]
    return "\n".join(parts)


def seen_key(sym: SymbolConfig, signal: Signal) -> str:
    return f"{sym.source}:{sym.symbol}:{sym.timeframe}:{signal.bar_time.isoformat()}:{signal.side}"


def scan_once(
    cfg: AppConfig,
    sources: Dict[str, DataSource],
    notifier: TelegramNotifier,
    seen: SeenStore,
) -> None:
    for sym in cfg.symbols:
        try:
            source = sources.get(sym.source)
            if source is None:
                log.warning(
                    "Symbol %s references unknown source '%s' -- skipping",
                    sym.symbol, sym.source,
                )
                continue

            df = source.fetch_ohlc(
                symbol=sym.symbol,
                timeframe=sym.timeframe,
                limit=cfg.history_bars,
            )
            min_needed = cfg.ichimoku_senkou_b + cfg.ichimoku_displacement + 5
            if len(df) < min_needed:
                log.info(
                    "Not enough bars for %s %s (%d < %d); skipping",
                    sym.symbol, sym.timeframe, len(df), min_needed,
                )
                continue

            df = compute_ichimoku(
                df,
                tenkan_period=cfg.ichimoku_tenkan,
                kijun_period=cfg.ichimoku_kijun,
                senkou_b_period=cfg.ichimoku_senkou_b,
                displacement=cfg.ichimoku_displacement,
            )

            signal = detect_signal(
                df,
                displacement=cfg.ichimoku_displacement,
                cross_lookback=cfg.cross_lookback_bars,
            )
            if signal is None:
                log.debug("%s %s: no signal", sym.symbol, sym.timeframe)
                continue

            key = seen_key(sym, signal)
            if seen.contains(key):
                log.debug("Already alerted for %s", key)
                continue

            msg = format_signal_message(sym, signal)
            notifier.send(msg)
            seen.add(key)
            log.info(
                "Signal sent: %s %s %s @ %s bar=%s",
                sym.symbol, sym.timeframe, signal.side,
                signal.entry_price, signal.bar_time,
            )

        except Exception as exc:  # noqa: BLE001
            log.exception("Error scanning %s %s: %s", sym.symbol, sym.timeframe, exc)
