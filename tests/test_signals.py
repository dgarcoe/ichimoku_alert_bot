"""
Synthetic unit test: build a price series that textbook-matches the video's
long setup, and verify detect_signal() fires on the Chikou breakout bar.

Run with:   python -m pytest tests/ -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.strategies import compute_ichimoku, detect_signal


def _make_ohlc(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """Build a minimal OHLC frame from a close series (OHL = close ± small eps)."""
    idx = pd.date_range(start=start, periods=len(closes), freq="1h", tz="UTC")
    close = np.asarray(closes, dtype=float)
    # Give each bar a tiny range so highs/lows aren't degenerate.
    high = close + np.maximum(np.abs(close) * 0.001, 0.01)
    low = close - np.maximum(np.abs(close) * 0.001, 0.01)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 0.0},
        index=idx,
    )


def test_long_setup_fires_on_chikou_breakout():
    """
    Shape of the series:
      - 60 bars of a steady downtrend (price falling)
      - ~15 bars of stabilization / gentle rise while still BELOW what will
        become the Kumo (that's when the Tenkan/Kijun bullish cross prints)
      - a strong rally that makes close[now] exceed high[now - 26]
        (the Chikou breakout the video describes)
    """
    rng = np.random.default_rng(42)

    # Phase 1: downtrend from 100 -> 60 over 60 bars.
    down = np.linspace(100.0, 60.0, 60) + rng.normal(0, 0.2, 60)

    # Phase 2: base / small rise from 60 -> 64 over 15 bars (T/K cross happens here).
    base = np.linspace(60.0, 64.0, 15) + rng.normal(0, 0.2, 15)

    # Phase 3: rally from 64 -> 95 over 35 bars. Somewhere in here, close
    # will exceed the high 26 bars earlier -> Chikou breakout.
    rally = np.linspace(64.0, 95.0, 35) + rng.normal(0, 0.2, 35)

    closes = np.concatenate([down, base, rally]).tolist()
    df = _make_ohlc(closes)
    df = compute_ichimoku(df)

    # Scan bar-by-bar from the earliest point where Ichimoku is fully defined,
    # and confirm that at least one LONG signal fires.
    min_len = 60  # senkou_b(52) + a bit of headroom
    fired = []
    for end in range(min_len, len(df) + 1):
        sig = detect_signal(df.iloc[:end])
        if sig is not None:
            fired.append(sig)

    assert fired, "Expected at least one signal on the constructed series."
    longs = [s for s in fired if s.side == "long"]
    assert longs, f"Expected a LONG signal, got only: {[s.side for s in fired]}"

    first = longs[0]
    # The cross that qualifies us must have happened strictly before the entry.
    assert first.cross_bar_time < first.bar_time
    # Stop must be below entry for a long.
    assert first.stop_loss < first.entry_price
    # Chikou breakout delta is positive by construction (close > past high).
    assert first.chikou_breakout_delta > 0


def test_flat_series_produces_no_signal():
    """A dead-flat market should never produce a Chikou breakout signal."""
    df = _make_ohlc([100.0] * 150)
    df = compute_ichimoku(df)
    for end in range(80, len(df) + 1):
        assert detect_signal(df.iloc[:end]) is None


def test_insufficient_data_returns_none():
    df = _make_ohlc([100.0 + i for i in range(20)])
    df = compute_ichimoku(df)
    assert detect_signal(df) is None
