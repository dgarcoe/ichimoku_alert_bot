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


@dataclass(frozen=True)
class StrategyOptions:
    # Optional filters are disabled until validated on out-of-sample data.
    min_breakout_atr: float = 0.0
    stop_buffer_atr: float = 0.0
    max_stop_pct: float = 0.0
    max_kijun_distance_atr: float = 0.0
    require_price_outside_cloud: bool = False
    require_projected_cloud: bool = False

    def __post_init__(self):
        import math
        for name in ("min_breakout_atr", "stop_buffer_atr", "max_stop_pct",
                     "max_kijun_distance_atr"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        for name in ("require_price_outside_cloud", "require_projected_cloud"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")


def detect_signal(df: pd.DataFrame, displacement: int = 26,
                  cross_lookback: int = 60,
                  options: Optional[StrategyOptions] = None) -> Optional[Signal]:
    """First Chikou breakout AFTER a still-active reversal cross, closed bars only.

    Equality in T/K invalidates the setup; a new directional cross may rearm it.
    The first breakout consumes the setup even if optional entry filters reject it.
    All comparisons use only present/past data; no plotted future Chikou column.
    """
    import math
    if displacement <= 0 or cross_lookback <= 0:
        raise ValueError("displacement and cross_lookback must be positive")
    options = options or StrategyOptions()
    if len(df) < displacement + 2:
        return None
    i = len(df) - 1
    row = df.iloc[i]
    required = ("close", "tenkan", "kijun", "kumo_top", "kumo_bottom")
    if not all(math.isfinite(row[c]) for c in required):
        return None
    diff = df.tenkan - df.kijun
    direction = 1 if diff.iloc[i] > 0 else -1 if diff.iloc[i] < 0 else 0
    if not direction:
        return None
    # Find the start of the current uninterrupted directional regime.
    cross_i = None
    for j in range(i, max(1, i-cross_lookback)-1, -1):
        if not math.isfinite(diff.iloc[j-1]):
            return None
        if direction * diff.iloc[j-1] <= 0:
            cross_i = j
            break
    if cross_i is None or cross_i == i or cross_i < displacement:
        return None
    cross = df.iloc[cross_i]
    if not all(math.isfinite(cross[c]) for c in required):
        return None
    # Strictly BELOW the whole cloud for long; ABOVE the whole cloud for short.
    if direction == 1 and not cross.close < cross.kumo_bottom:
        return None
    if direction == -1 and not cross.close > cross.kumo_top:
        return None
    reference = df.high if direction == 1 else df.low
    def clearance(j):
        return direction * (df.close.iloc[j] - reference.iloc[j-displacement])
    if not (clearance(i-1) <= 0 < clearance(i)):
        return None
    # One opportunity per setup (also deterministic across process restarts).
    if any(clearance(j-1) <= 0 < clearance(j) for j in range(cross_i+1, i)):
        return None
    atr = row.get("atr", float("nan"))
    if any((options.min_breakout_atr, options.stop_buffer_atr,
            options.max_kijun_distance_atr)) and (not math.isfinite(atr) or atr <= 0):
        return None
    if options.min_breakout_atr and clearance(i) < options.min_breakout_atr * atr:
        return None
    if options.max_kijun_distance_atr and abs(row.close-row.kijun) > options.max_kijun_distance_atr * atr:
        return None
    if options.require_price_outside_cloud:
        boundary = row.kumo_top if direction == 1 else row.kumo_bottom
        if direction * (row.close-boundary) <= 0:
            return None
    if options.require_projected_cloud:
        a, b = row.get("projected_senkou_a"), row.get("projected_senkou_b")
        if a is None or b is None or not math.isfinite(a+b) or direction*(a-b) <= 0:
            return None
    swing = df.iloc[cross_i:i+1]
    stop = min(row.kijun, swing.low.min()) if direction == 1 else max(row.kijun, swing.high.max())
    if options.stop_buffer_atr:
        stop -= direction * options.stop_buffer_atr * atr
    risk = direction * (row.close-stop)
    if not math.isfinite(stop) or stop <= 0 or risk <= 0:
        return None
    if options.max_stop_pct and risk / row.close * 100 > options.max_stop_pct:
        return None
    return Signal(
        side="long" if direction == 1 else "short", bar_time=df.index[i],
        entry_price=float(row.close), stop_loss=float(stop),
        tenkan=float(row.tenkan), kijun=float(row.kijun),
        kumo_top=float(row.kumo_top), kumo_bottom=float(row.kumo_bottom),
        chikou_breakout_delta=float(clearance(i)), cross_bar_time=df.index[cross_i],
    )
