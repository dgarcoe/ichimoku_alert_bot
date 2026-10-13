"""Shared, fail-closed OHLC validation."""
import numpy as np
import pandas as pd


def validate_ohlc(df: pd.DataFrame) -> None:
    required = ['open', 'high', 'low', 'close']
    if not set(required).issubset(df.columns):
        raise ValueError('Missing OHLC columns')
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.hasnans:
        raise ValueError('OHLC requires a valid DatetimeIndex')
    if not df.index.is_monotonic_increasing or not df.index.is_unique:
        raise ValueError('OHLC timestamps must be unique and ascending')
    values = df[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('OHLC prices must be finite and positive')
    if ((df.high < df[['open', 'close', 'low']].max(axis=1)) |
            (df.low > df[['open', 'close', 'high']].min(axis=1))).any():
        raise ValueError('Inconsistent OHLC candle bounds')
