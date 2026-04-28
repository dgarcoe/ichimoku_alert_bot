"""
Yahoo Finance OHLC via the `yfinance` library. No API key, no signup.

Symbol conventions on Yahoo:
  - Forex pairs end with "=X" (EURUSD=X, GBPUSD=X, USDJPY=X, ...)
  - Crypto pairs use a dash (BTC-USD, ETH-USD, SOL-USD, ...)
  - Equities/futures/indices use their normal Yahoo tickers

Limits to be aware of (Yahoo's own, not yfinance's):
  - 1m candles: only the last 7 days
  - 2m..90m candles: only the last 60 days
  - 1h candles: up to ~730 days
  - Daily and above: years of history

We accept friendly forms ("EUR/USD", "EURUSD", "BTCUSDT") and translate to
Yahoo's form. For "BTCUSDT" we strip the trailing "T" so it becomes BTC-USD.

Yahoo doesn't natively offer 2h/4h/6h/8h/12h bars. For those timeframes we
fetch 1h bars and resample, so users can run the same Ichimoku setups on
forex/equities (Yahoo) that they run on crypto (Binance).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd
import yfinance as yf

from ..timeframes import interval_seconds
from .base import DataSource

log = logging.getLogger(__name__)


# Timeframes Yahoo supports natively, mapped to yfinance's interval string.
# yfinance accepted intervals: 1m 2m 5m 15m 30m 60m 90m 1h 1d 5d 1wk 1mo 3mo
_NATIVE_TIMEFRAME_MAP: Dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",   # yfinance accepts both, '60m' is the canonical one
    "1d": "1d",
    "1w": "1wk",
}

# Timeframes we synthesize by resampling 1h bars. Values are pandas offset
# aliases passed to DataFrame.resample().
_RESAMPLE_FROM_1H: Dict[str, str] = {
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
}

# How far back we ask for, per timeframe. Must be <= Yahoo's own limit.
_PERIOD_FOR: Dict[str, str] = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "60d",   # ~1440 hourly bars -- plenty for Ichimoku
    # Synthetic multi-hour timeframes pull 1h bars then resample. Yahoo allows
    # 1h up to ~730 days, which yields plenty of bars even for 12h.
    "2h": "730d",
    "4h": "730d",
    "6h": "730d",
    "8h": "730d",
    "12h": "730d",
    "1d": "2y",
    "1w": "10y",
}


def _to_yahoo_symbol(symbol: str) -> str:
    """Translate friendly symbol forms into Yahoo's ticker convention."""
    s = symbol.strip().upper()

    # Already Yahoo-formatted? Keep as-is.
    if s.endswith("=X") or "-" in s or "=" in s:
        return s

    # Forex with slash: EUR/USD -> EURUSD=X
    if "/" in s:
        return s.replace("/", "") + "=X"

    # 6-letter all-caps code that doesn't end in T  ->  forex (EURUSD -> EURUSD=X)
    if len(s) == 6 and s.isalpha():
        return s + "=X"

    # Crypto Binance-style: BTCUSDT -> BTC-USD,  ETHUSDT -> ETH-USD
    if s.endswith("USDT"):
        return s[:-4] + "-USD"
    if s.endswith("USDC"):
        return s[:-4] + "-USD"

    # Fall back: assume the caller already gave a valid Yahoo ticker.
    return s


class YahooSource(DataSource):
    """OHLC from Yahoo Finance via the yfinance library."""

    name = "yahoo"

    def fetch_ohlc(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        interval, resample_rule = _resolve_timeframe(timeframe)

        ticker = _to_yahoo_symbol(symbol)
        period = _PERIOD_FOR[timeframe]

        log.debug(
            "Yahoo download: %s interval=%s period=%s resample=%s",
            ticker, interval, period, resample_rule,
        )

        df = yf.download(
            tickers=ticker,
            interval=interval,
            period=period,
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df is None or df.empty:
            log.warning("Yahoo returned no data for %s (%s)", ticker, interval)
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            ).astype(float)

        # yfinance sometimes returns a MultiIndex on columns (when multiple
        # tickers are requested). Flatten just in case.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )

        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        df = df[keep].copy()

        # Yahoo intraday timestamps are tz-aware; daily are naive. Normalize.
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df.index.name = "timestamp"

        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_index()

        if resample_rule is not None:
            df = _resample_ohlc(df, resample_rule)

        # Drop the still-forming bar if its timestamp looks too recent.
        if len(df) > 0:
            last_ts = df.index[-1]
            now = pd.Timestamp.now(tz="UTC")
            if (now - last_ts).total_seconds() < interval_seconds(timeframe):
                df = df.iloc[:-1]

        return df.tail(limit)


def _resolve_timeframe(timeframe: str) -> tuple[str, Optional[str]]:
    """Return (yfinance interval, resample rule or None) for a requested tf."""
    if timeframe in _NATIVE_TIMEFRAME_MAP:
        return _NATIVE_TIMEFRAME_MAP[timeframe], None
    if timeframe in _RESAMPLE_FROM_1H:
        return "60m", _RESAMPLE_FROM_1H[timeframe]
    raise ValueError(f"Unsupported timeframe for Yahoo: {timeframe}")


def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate finer-grained OHLC bars into the requested rule (e.g. '4h')."""
    agg: Dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        agg["volume"] = "sum"

    # label/closed='left' makes the bar timestamp mark the open time, which
    # is the convention used by Binance and by the rest of this codebase.
    out = df.resample(rule, label="left", closed="left").agg(agg)
    return out.dropna(subset=["open", "high", "low", "close"])


