"""Offline single-symbol backtest; fixed initial stop, R target, next-open fills.

Not a broker simulator. No leverage, funding, borrow, spread model or portfolio.
Reports net R, not a compounded return. Provide only completed candles.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass

import pandas as pd

from .strategies import compute_ichimoku, detect_signal
from .strategies.signals import StrategyOptions


@dataclass(frozen=True)
class Trade:
    side: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry: float
    exit: float
    stop: float
    target: float
    reason: str
    net_r: float


def _exit_price(bar, direction, stop, target):
    """Opening gaps first; stop wins when both levels touched intrabar."""
    if direction * (bar.open-stop) <= 0:
        return bar.open, 'stop_gap'
    if direction * (bar.open-target) >= 0:
        return target, 'target_gap'  # conservative: no positive gap improvement
    adverse = bar.low if direction == 1 else bar.high
    favorable = bar.high if direction == 1 else bar.low
    if direction * (adverse-stop) <= 0:
        return stop, 'stop'
    if direction * (favorable-target) >= 0:
        return target, 'target'
    return None


def run_backtest(df, *, options=None, displacement=26, cross_lookback=60,
                 tenkan_period=9, kijun_period=26, senkou_b_period=52,
                 reward_r=2.0, fee_bps=10.0, slippage_bps=5.0,
                 max_holding_bars=100, signal_start=None):
    for name, value in [('reward_r', reward_r), ('fee_bps', fee_bps),
                        ('slippage_bps', slippage_bps)]:
        if not math.isfinite(value) or value < 0:
            raise ValueError(f'{name} must be finite and nonnegative')
    if reward_r <= 0 or max_holding_bars <= 0 or slippage_bps >= 10000:
        raise ValueError('Invalid reward, holding period or slippage')
    features = compute_ichimoku(df, tenkan_period, kijun_period,
                               senkou_b_period, displacement)
    trades = []
    position = None
    slip, fee = slippage_bps / 10000, fee_bps / 10000
    for i in range(1, len(features)):
        bar = features.iloc[i]
        if position is None and (signal_start is None or features.index[i-1] >= signal_start):
            sig = detect_signal(features.iloc[:i], displacement, cross_lookback, options)
            if sig is not None:
                d = 1 if sig.side == 'long' else -1
                entry = bar.open * (1+d*slip)
                risk = d * (entry-sig.stop_loss)
                # A gap through the stop invalidates the entry.
                max_pct = (options or StrategyOptions()).max_stop_pct
                if risk > 0 and d*(bar.open-sig.stop_loss) > 0 and (not max_pct or risk/entry*100 <= max_pct):
                    target = entry+d*reward_r*risk
                    if target > 0:
                        position = (sig, d, entry, risk, target, i)
        if position is None:
            continue
        sig, d, entry, risk, target, start = position
        result = _exit_price(bar, d, sig.stop_loss, target)
        if result is None and (i-start+1 >= max_holding_bars or i == len(features)-1):
            result = (bar.close, 'timeout' if i-start+1 >= max_holding_bars else 'end_of_data')
        if result is None:
            continue
        price, reason = result
        # Target is a resting limit; slippage applies to market/stop exits only.
        exit_price = price if reason.startswith('target') else price*(1-d*slip)
        net_r = (d*(exit_price-entry)-fee*(entry+exit_price))/risk
        trades.append(Trade(sig.side, sig.bar_time.isoformat(), features.index[start].isoformat(),
                            features.index[i].isoformat(), float(entry), float(exit_price),
                            sig.stop_loss, float(target), reason, float(net_r)))
        position = None
    return trades


def summarize(trades):
    values = [t.net_r for t in trades]
    gains = sum(max(v, 0) for v in values)
    losses = -sum(min(v, 0) for v in values)
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak-equity)
    return dict(trades=len(values), win_rate=sum(v > 0 for v in values)/len(values) if values else None,
                net_r=sum(values), expectancy_r=sum(values)/len(values) if values else None,
                profit_factor=gains/losses if losses else None,
                max_closed_trade_drawdown_r=drawdown)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', help='timestamp,open,high,low,close[,volume], ascending UTC')
    parser.add_argument('--config', help='Reuse Ichimoku and strategy parameters from YAML')
    parser.add_argument('--fee-bps', type=float, default=10)
    parser.add_argument('--slippage-bps', type=float, default=5)
    parser.add_argument('--reward-r', type=float, default=2)
    parser.add_argument('--max-holding-bars', type=int, default=100)
    parser.add_argument('--test-start', help='Only report trades signalled at/after this UTC time; prior rows warm up indicators')
    parser.add_argument('--trades-csv', help='Optional trade ledger output')
    args = parser.parse_args()
    df = pd.read_csv(args.csv)
    df.index = pd.to_datetime(df.pop('timestamp'), utc=True)
    kwargs = {}
    if args.config:
        from .config import load_config
        cfg = load_config(args.config)
        kwargs = dict(options=cfg.strategy, displacement=cfg.ichimoku_displacement,
                      cross_lookback=cfg.cross_lookback_bars, tenkan_period=cfg.ichimoku_tenkan,
                      kijun_period=cfg.ichimoku_kijun, senkou_b_period=cfg.ichimoku_senkou_b)
    # Keep warmup data but suppress pre-test entries rather than carrying an
    # in-sample position into the evaluation period.
    if args.test_start:
        start = pd.to_datetime(args.test_start, utc=True)
        test_idx = df.index.searchsorted(start)
        if test_idx >= len(df):
            raise ValueError('test-start is after the data')
        kwargs['signal_start'] = start
    trades = run_backtest(df, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
                          reward_r=args.reward_r, max_holding_bars=args.max_holding_bars, **kwargs)
    print(json.dumps(summarize(trades), indent=2, allow_nan=False))
    if args.trades_csv:
        pd.DataFrame([asdict(t) for t in trades], columns=list(Trade.__dataclass_fields__)).to_csv(args.trades_csv, index=False)


if __name__ == '__main__':
    main()
