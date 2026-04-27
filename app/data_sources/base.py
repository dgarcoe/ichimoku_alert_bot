"""OHLC data provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataSource(ABC):
    """Abstract OHLC source. Subclasses fetch candles for a symbol/timeframe."""

    # Map of friendly timeframe -> provider-specific string.
    # Subclasses override in their own fetch methods.
    name: str = "base"

    @abstractmethod
    def fetch_ohlc(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """
        Return a DataFrame indexed by UTC timestamp with columns
        ['open', 'high', 'low', 'close', 'volume'], ascending order,
        excluding the currently-forming bar (only CLOSED bars).
        """
        ...
