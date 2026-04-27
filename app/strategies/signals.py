"""
Chikou Span Breakout after Tenkan/Kijun cross.

Strategy (from the reference video):

LONG:
  1. Prior downtrend (price was below Kijun / under bearish Kumo).
  2. Tenkan-sen crosses above Kijun-sen while price is still below Kumo
     (early momentum shift -- do NOT enter yet).
  3. Wait for Chikou Span to break above the past price candles at its
     own chart position (i.e. close_now > high[now - displacement]).
  4. Entry = the breakout bar. Stop-loss = below Kijun-sen or swing low.

SHORT: mirror image.

This module does not place orders. It scans the last N bars for a completed
setup and returns a Signal describing what happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd


SignalSide = Literal["long", "short"]


@dataclass
class Signal:
    side: SignalSide
    bar_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    tenkan: float
    kijun: float
    kumo_top: float
    kumo_bottom: float
    # Distance used by Chikou to "break" past price (in price units). Useful as
    # a rough strength gauge -- a clean breakout is better than a marginal one.
    chikou_breakout_delta: float
    # Bar index of the Tenkan/Kijun cross that led to this signal (for context).
    cross_bar_time: pd.Timestamp

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "bar_time": self.bar_time.isoformat(),
            "entry_price": round(self.entry_price, 8),
            "stop_loss": round(self.stop_loss, 8),
            "tenkan": round(self.tenkan, 8),
            "kijun": round(self.kijun, 8),
            "kumo_top": round(self.kumo_top, 8),
            "kumo_bottom": round(self.kumo_bottom, 8),
            "chikou_breakout_delta": round(self.chikou_breakout_delta, 8),
            "cross_bar_time": self.cross_bar_time.isoformat(),
        }


def _last_cross_index(
    df: pd.DataFrame, up_to: int, side: SignalSide, max_lookback: int
) -> Optional[int]:
    """
    Find the most recent Tenkan/Kijun cross before (or at) index `up_to`.

    For 'long'  we want a bullish cross: tenkan crosses above kijun.
    For 'short' we want a bearish cross: tenkan crosses below kijun.

    Returns the integer index of the cross bar, or None if not found within
    max_lookback bars.
    """
    tenkan = df["tenkan"].to_numpy()
    kijun = df["kijun"].to_numpy()

    start = max(1, up_to - max_lookback)
    for i in range(up_to, start - 1, -1):
        prev_diff = tenkan[i - 1] - kijun[i - 1]
        curr_diff = tenkan[i] - kijun[i]
        if pd.isna(prev_diff) or pd.isna(curr_diff):
            continue
        if side == "long" and prev_diff <= 0 and curr_diff > 0:
            return i
        if side == "short" and prev_diff >= 0 and curr_diff < 0:
            return i
    return None


def detect_signal(
    df: pd.DataFrame,
    displacement: int = 26,
    cross_lookback: int = 60,
) -> Optional[Signal]:
    """
    Look at the most recently *closed* bar and decide whether it is a Chikou
    Span Breakout entry bar following a qualifying Tenkan/Kijun cross.

    Parameters
    ----------
    df : DataFrame with OHLC + Ichimoku columns, ascending by time.
         The caller is responsible for passing only CLOSED bars.
    displacement : Ichimoku displacement (default 26).
    cross_lookback : how many bars back to look for the qualifying cross.

    Returns
    -------
    Signal if the latest bar is a fresh entry; otherwise None.
    """
    # We need at least displacement + 1 bars so the Chikou at the latest bar
    # has a past candle to be compared against.
    if len(df) < displacement + 2:
        return None

    i = len(df) - 1  # index of the most recent closed bar

    # Chikou at chart position (i - displacement) equals close[i].
    chikou_now = df["close"].iloc[i]
    past_idx = i - displacement
    if past_idx < 1:
        return None

    past_high = df["high"].iloc[past_idx]
    past_low = df["low"].iloc[past_idx]
    prev_past_idx = past_idx - 1
    prev_past_high = df["high"].iloc[prev_past_idx]
    prev_past_low = df["low"].iloc[prev_past_idx]

    # Previous bar's Chikou (close[i-1] projected to past_idx - 1).
    chikou_prev = df["close"].iloc[i - 1]

    kumo_top = df["kumo_top"].iloc[i]
    kumo_bottom = df["kumo_bottom"].iloc[i]
    tenkan = df["tenkan"].iloc[i]
    kijun = df["kijun"].iloc[i]
    close_now = df["close"].iloc[i]

    if any(pd.isna(x) for x in (kumo_top, kumo_bottom, tenkan, kijun)):
        return None

    # ---------- LONG ----------
    # Chikou crosses above the past candle's high on this bar.
    bullish_break = chikou_prev <= prev_past_high and chikou_now > past_high
    if bullish_break:
        cross_i = _last_cross_index(df, i, side="long", max_lookback=cross_lookback)
        if cross_i is not None:
            cross_close = df["close"].iloc[cross_i]
            cross_kumo_top = df["kumo_top"].iloc[cross_i]
            # Per the video: the qualifying cross happens BELOW the Kumo so
            # we are catching a reversal from a downtrend.
            if pd.notna(cross_kumo_top) and cross_close < cross_kumo_top:
                swing_low = df["low"].iloc[cross_i : i + 1].min()
                stop = min(kijun, swing_low)
                return Signal(
                    side="long",
                    bar_time=df.index[i],
                    entry_price=float(close_now),
                    stop_loss=float(stop),
                    tenkan=float(tenkan),
                    kijun=float(kijun),
                    kumo_top=float(kumo_top),
                    kumo_bottom=float(kumo_bottom),
                    chikou_breakout_delta=float(chikou_now - past_high),
                    cross_bar_time=df.index[cross_i],
                )

    # ---------- SHORT ----------
    bearish_break = chikou_prev >= prev_past_low and chikou_now < past_low
    if bearish_break:
        cross_i = _last_cross_index(df, i, side="short", max_lookback=cross_lookback)
        if cross_i is not None:
            cross_close = df["close"].iloc[cross_i]
            cross_kumo_bottom = df["kumo_bottom"].iloc[cross_i]
            # Mirror: qualifying bearish cross happens ABOVE the Kumo.
            if pd.notna(cross_kumo_bottom) and cross_close > cross_kumo_bottom:
                swing_high = df["high"].iloc[cross_i : i + 1].max()
                stop = max(kijun, swing_high)
                return Signal(
                    side="short",
                    bar_time=df.index[i],
                    entry_price=float(close_now),
                    stop_loss=float(stop),
                    tenkan=float(tenkan),
                    kijun=float(kijun),
                    kumo_top=float(kumo_top),
                    kumo_bottom=float(kumo_bottom),
                    chikou_breakout_delta=float(past_low - chikou_now),
                    cross_bar_time=df.index[cross_i],
                )

    return None
