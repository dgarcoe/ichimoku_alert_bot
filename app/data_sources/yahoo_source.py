"""
Yahoo Finance OHLC via the `yfinance` library. No API key, no signup.

Symbol conventions on Yahoo:
  - Forex pairs end with "=X" (EURUSD=X, GBPUSD=X, USDJPY=X, ...)
  - Crypto pairs use a dash (BTC-USD, ETH-USD, SOL-USD, ...)
  - Equities/futures/indices use their normal Yahoo tickers

Limits to be aware of (Yahoo's own, not yfinance's):
  - 1m candles: only the last 7 days
  - All sub-daily intervals (<1d): only the last 60 days
  - Daily and above: years of history

We accept friendly forms ("EUR/USD", "EURUSD", "BTCUSDT") and translate to
Yahoo's form. For "BTCUSDT" we strip the trailing "T" so it becomes BTC-USD.
"""

from __future__ import annotations

import logging
from typing import Dict

import pandas as pd
import yfinance as yf

from .base import DataSource

log = logging.getLogger(__name__)


# yfinance accepted intervals: 1m 2m 5m 15m 30m 60m 90m 1h 1d 5d 1wk 1mo 3mo
_TIMEFRAME_MAP: Dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",   # yfinance accepts both, '60m' is the canonical one
    "1d": "1d",
    "1w": "1wk",
}

# How far back we ask for, per timeframe. Must be <= Yahoo's own limit.
_PERIOD_FOR: Dict[str, str] = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "60d",   # ~1440 hourly bars -- plenty for Ichimoku
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
        if timeframe not in _TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe for Yahoo: {timeframe}")

        ticker = _to_yahoo_symbol(symbol)
        interval = _TIMEFRAME_MAP[timeframe]
        period = _PERIOD_FOR[timeframe]

        log.debug("Yahoo download: %s interval=%s period=%s", ticker, interval, period)

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

        # Drop the still-forming bar if its timestamp looks too recent.
        if len(df) > 0:
            last_ts = df.index[-1]
            now = pd.Timestamp.now(tz="UTC")
            interval_seconds = _interval_seconds(timeframe)
            if (now - last_ts).total_seconds() < interval_seconds:
                df = df.iloc[:-1]

        return df.tail(limit)


def _interval_seconds(timeframe: str) -> int:
    table = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "1d": 86400, "1w": 604800,
    }
    return table[timeframe]
