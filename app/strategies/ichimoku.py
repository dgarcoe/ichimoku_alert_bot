"""
Ichimoku Kinko Hyo indicator calculations.

Standard settings (Goichi Hosoda's original):
  - Tenkan-sen (Conversion):  (9-period high + 9-period low) / 2
  - Kijun-sen  (Base):         (26-period high + 26-period low) / 2
  - Senkou A   (Lead A):       (Tenkan + Kijun) / 2, plotted 26 periods ahead
  - Senkou B   (Lead B):       (52-period high + 52-period low) / 2, plotted 26 periods ahead
  - Chikou Span (Lagging):     Close plotted 26 periods behind

The pair (Senkou A, Senkou B) forms the Kumo (cloud).
"""

from __future__ import annotations

import pandas as pd


def compute_ichimoku(
    df: pd.DataFrame,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> pd.DataFrame:
    """
    Compute Ichimoku components and append them to the input DataFrame.

    Expects columns: ['open', 'high', 'low', 'close'] indexed by timestamp (ascending).

    Returns a copy of df with added columns:
        tenkan, kijun, senkou_a, senkou_b, chikou,
        kumo_top, kumo_bottom, price_above_kumo, price_below_kumo
    """
    out = df.copy()

    high = out["high"]
    low = out["low"]
    close = out["close"]

    # Tenkan-sen (Conversion Line)
    out["tenkan"] = (
        high.rolling(window=tenkan_period).max()
        + low.rolling(window=tenkan_period).min()
    ) / 2

    # Kijun-sen (Base Line)
    out["kijun"] = (
        high.rolling(window=kijun_period).max()
        + low.rolling(window=kijun_period).min()
    ) / 2

    # Senkou Span A (Leading Span A) -- shifted forward by `displacement`
    out["senkou_a"] = ((out["tenkan"] + out["kijun"]) / 2).shift(displacement)

    # Senkou Span B (Leading Span B) -- shifted forward by `displacement`
    out["senkou_b"] = (
        (
            high.rolling(window=senkou_b_period).max()
            + low.rolling(window=senkou_b_period).min()
        )
        / 2
    ).shift(displacement)

    # Chikou Span (Lagging Span) -- close plotted `displacement` periods behind.
    # We shift(-displacement) so that row i contains the close that will be
    # "at" position i - displacement on the chart (i.e. the chikou value whose
    # chart-x is `i - displacement` lives at dataframe index `i`).
    out["chikou"] = close.shift(-displacement)

    # Kumo boundaries at each bar (uses the values that project to that bar)
    out["kumo_top"] = out[["senkou_a", "senkou_b"]].max(axis=1)
    out["kumo_bottom"] = out[["senkou_a", "senkou_b"]].min(axis=1)

    out["price_above_kumo"] = close > out["kumo_top"]
    out["price_below_kumo"] = close < out["kumo_bottom"]

    return out
