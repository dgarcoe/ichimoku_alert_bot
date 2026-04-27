"""
End-to-end smoke test against live Binance data. No Telegram calls.
Run from repo root:  python scripts/smoke_binance.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data_sources import BinanceSource
from app.strategies import compute_ichimoku, detect_signal


def main() -> int:
    source = BinanceSource()
    for symbol, tf in [("BTCUSDT", "4h"), ("BTCUSDT", "1d"), ("ETHUSDT", "4h")]:
        print(f"\n--- {symbol} {tf} ---")
        df = source.fetch_ohlc(symbol=symbol, timeframe=tf, limit=200)
        print(f"  bars fetched : {len(df)}")
        print(f"  first bar    : {df.index[0] if len(df) else 'N/A'}")
        print(f"  last bar     : {df.index[-1] if len(df) else 'N/A'}")

        ichi = compute_ichimoku(df)
        last = ichi.iloc[-1]
        print(f"  close        : {last['close']:.2f}")
        print(f"  tenkan       : {last['tenkan']:.2f}")
        print(f"  kijun        : {last['kijun']:.2f}")
        print(f"  kumo top/bot : {last['kumo_top']:.2f} / {last['kumo_bottom']:.2f}")

        sig = detect_signal(ichi)
        if sig is None:
            print("  signal       : none on the latest closed bar")
        else:
            print(f"  signal       : {sig.side.upper()} @ {sig.entry_price:.2f}")
            print(f"  stop         : {sig.stop_loss:.2f}")
            print(f"  bar          : {sig.bar_time}")
            print(f"  qual. cross  : {sig.cross_bar_time}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
