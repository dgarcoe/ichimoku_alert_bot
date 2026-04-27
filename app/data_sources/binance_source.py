"""
Binance public spot klines -- free, no API key needed.

Endpoint: GET https://api.binance.com/api/v3/klines
Docs: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
"""

from __future__ import annotations

import logging
from typing import Dict

import httpx
import pandas as pd

from .base import DataSource

log = logging.getLogger(__name__)


# Binance supports: 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M
_TIMEFRAME_MAP: Dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "1w": "1w",
}


class BinanceSource(DataSource):
    name = "binance"

    def __init__(self, base_url: str = "https://api.binance.com", timeout: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def fetch_ohlc(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        if timeframe not in _TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe for Binance: {timeframe}")

        # Binance uses symbols like "BTCUSDT" (no separator). Accept "BTC/USDT" too.
        sym = symbol.replace("/", "").replace("-", "").upper()

        # +1 so we can drop the currently-forming bar and still return `limit`.
        params = {
            "symbol": sym,
            "interval": _TIMEFRAME_MAP[timeframe],
            "limit": min(limit + 1, 1000),
        }

        url = f"{self._base_url}/api/v3/klines"
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            raw = resp.json()

        if not raw:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            ).astype(float)

        # Kline fields: [openTime, open, high, low, close, volume, closeTime, ...]
        df = pd.DataFrame(
            raw,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_base_volume", "taker_quote_volume", "ignore",
            ],
        )

        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
        df = df.sort_index()

        # Drop the still-forming candle. Binance includes it if we're inside
        # the interval; the safest thing is always to drop the last bar.
        if len(df) > 0:
            df = df.iloc[:-1]

        return df.tail(limit)
