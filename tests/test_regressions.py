import json
from unittest.mock import Mock

import httpx
import numpy as np
import pandas as pd
import pytest

from app.strategies import compute_ichimoku, detect_signal
from app.strategies.signals import StrategyOptions
from app.state import SeenStore
from app.data_sources.yahoo_source import _to_yahoo_symbol, _resample_ohlc
from app.notifiers.telegram import TelegramNotifier
from app.backtest import _exit_price, run_backtest, summarize
from tests.test_signals import _make_ohlc


def setup_frame(short=False):
    # Small hand-computed fixture: d=2, cross=4, first breakout=6.
    df = pd.DataFrame(dict(open=[100,100,100,80,80,80,82],
                           high=[101,101,101,81,81,81,83],
                           low=[99,99,99,79,79,79,81],
                           close=[100,100,100,80,80,80,82],
                           tenkan=[89,89,89,89,91,91,91],
                           kijun=[90]*7, kumo_top=[110]*7,
                           kumo_bottom=[105]*7, atr=[2]*7,
                           projected_senkou_a=[100]*7,
                           projected_senkou_b=[99]*7),
                      index=pd.date_range('2024-01-01', periods=7, freq='h', tz='UTC'))
    if short:
        out = df.copy()
        for c in ['open','close','tenkan','kijun','projected_senkou_a','projected_senkou_b']:
            out[c] = 200-df[c]
        out['high'], out['low'] = 200-df.low, 200-df.high
        out['kumo_top'], out['kumo_bottom'] = 200-df.kumo_bottom, 200-df.kumo_top
        return out
    return df


@pytest.mark.parametrize('short', [False, True])
def test_strict_setup_and_direction(short):
    df = setup_frame(short)
    signal = detect_signal(df, 2)
    assert signal.side == ('short' if short else 'long')
    assert signal.cross_bar_time == df.index[4]
    assert signal.bar_time == df.index[6]
    assert (signal.entry_price-signal.stop_loss)*(1 if not short else -1) > 0


@pytest.mark.parametrize('short', [False, True])
def test_inside_cloud_is_not_outside(short):
    df = setup_frame(short)
    df.loc[df.index[4], ['kumo_bottom','kumo_top']] = [70, 90] if not short else [110,130]
    assert detect_signal(df, 2) is None


def test_opposite_or_flat_tk_invalidates_old_cross():
    df = setup_frame()
    df.loc[df.index[5]:, 'tenkan'] = 89
    assert detect_signal(df, 2) is None
    df.loc[df.index[5]:, 'tenkan'] = 90
    assert detect_signal(df, 2) is None


def test_same_bar_cross_is_not_sequence():
    df = setup_frame()
    df.loc[df.index[4:6], 'tenkan'] = 89
    assert detect_signal(df, 2) is None


def test_expired_cross():
    assert detect_signal(setup_frame(), 2, cross_lookback=1) is None


def test_only_first_breakout_consumes_setup():
    df = setup_frame()
    extra = df.iloc[[-1,-1]].copy()
    extra.index = pd.date_range(df.index[-1]+pd.Timedelta(hours=1), periods=2, freq='h')
    extra['close'] = [80,84]
    extra['high'] = [81,85]
    extra['low'] = [79,83]
    extra['open'] = extra.close
    assert detect_signal(pd.concat([df, extra]), 2) is None


def test_filters_and_stop_buffer():
    df = setup_frame()
    assert detect_signal(df, 2, options=StrategyOptions(min_breakout_atr=1)) is None
    assert detect_signal(df, 2, options=StrategyOptions(require_price_outside_cloud=True)) is None
    assert detect_signal(df, 2, options=StrategyOptions(max_stop_pct=1)) is None
    assert detect_signal(df, 2, options=StrategyOptions(max_kijun_distance_atr=1)) is None
    a = detect_signal(df, 2)
    b = detect_signal(df, 2, options=StrategyOptions(stop_buffer_atr=0.5))
    assert b.stop_loss == a.stop_loss - 1
    df['projected_senkou_a'] = 98
    assert detect_signal(df, 2, options=StrategyOptions(require_projected_cloud=True)) is None


def test_features_are_prefix_invariant_no_future_leak():
    df = _make_ohlc((100+np.sin(np.arange(180)/10)*20).tolist())
    full = compute_ichimoku(df)
    for end in [60, 80, 100, 150]:
        prefix = compute_ichimoku(df.iloc[:end])
        pd.testing.assert_frame_equal(prefix, full.iloc[:end])
        assert detect_signal(prefix) == detect_signal(full.iloc[:end])
    assert full.kumo_top.iloc[:77].isna().all()
    assert full.kumo_top.iloc[77:].notna().all()
    assert full.chikou.equals(full.close)


@pytest.mark.parametrize('kind', ['duplicate','reverse','nan','infinite','bounds'])
def test_bad_ohlc_rejected(kind):
    df = _make_ohlc([100.0]*100)
    if kind == 'duplicate': df.index = pd.DatetimeIndex([df.index[0]]*len(df))
    if kind == 'reverse': df = df.iloc[::-1]
    if kind == 'nan': df.iloc[5,0] = np.nan
    if kind == 'infinite': df.iloc[5,0] = np.inf
    if kind == 'bounds': df.iloc[5,0] = 200
    with pytest.raises(ValueError): compute_ichimoku(df)


def test_state_order_bound_reload_and_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = SeenStore('state.json', max_entries=2)
    for k in ['a','b','c']: store.add(k)
    assert not store.contains('a')
    assert json.loads((tmp_path/'state.json').read_text()) == ['b','c']
    assert SeenStore('state.json', 2).contains('c')


@pytest.mark.parametrize('symbol,expected', [('BTC/USDT','BTC-USD'),('OPUSDT','OP-USD'),
    ('EUR/USD','EURUSD=X'),('BTC/USD','BTC-USD'),('EURUSD','EURUSD=X'),('GOOGL','GOOGL')])
def test_yahoo_symbols(symbol, expected):
    assert _to_yahoo_symbol(symbol) == expected


def test_partial_resample_is_dropped():
    df = _make_ohlc([100.0]*9).drop(_make_ohlc([100.0]*9).index[2])
    out = _resample_ohlc(df, '4h')
    assert list(out.index) == [pd.Timestamp('2024-01-01T04:00Z')]


def mock_http(monkeypatch, module, handler):
    real = httpx.Client
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: real(transport=httpx.MockTransport(handler)))


def test_telegram_partial_delivery_and_no_token_leak(monkeypatch, caplog):
    from app.notifiers import telegram
    def handler(request):
        chat = json.loads(request.content)['chat_id']
        if chat == 'a': return httpx.Response(200, json={'ok':True})
        raise httpx.ConnectError('secret-token in URL', request=request)
    mock_http(monkeypatch, telegram, handler)
    notifier = TelegramNotifier('secret-token', ['a','b'])
    assert notifier.send('test') == {'a'}
    assert 'secret-token' not in caplog.text


def test_binance_keeps_closed_last_and_drops_open(monkeypatch):
    from app.data_sources import binance_source
    now = pd.Timestamp.now(tz='UTC').floor('h')
    def row(ts):
        ms = ts.value//1_000_000
        return [ms,'100','101','99','100','1',ms+3599999,'1',1,'1','1','0']
    payload = [row(now-pd.Timedelta(hours=2)), row(now-pd.Timedelta(hours=1))]
    mock_http(monkeypatch, binance_source, lambda req: httpx.Response(200, json=payload))
    source = binance_source.BinanceSource()
    assert len(source.fetch_ohlc('BTCUSDT','1h')) == 2
    payload.append(row(now))
    assert len(source.fetch_ohlc('BTCUSDT','1h')) == 2


def test_exit_ambiguity_and_gaps():
    assert _exit_price(pd.Series(dict(open=100,low=89,high=121)),1,90,120) == (90,'stop')
    assert _exit_price(pd.Series(dict(open=85,low=80,high=121)),1,90,120) == (85,'stop_gap')
    assert _exit_price(pd.Series(dict(open=100,low=79,high=111)),-1,110,80) == (110,'stop')


def test_backtest_next_open_and_costs(monkeypatch):
    from app import backtest
    sig = detect_signal(setup_frame(), 2)
    df = _make_ohlc([82.,84.,86.,88.])
    monkeypatch.setattr(backtest, 'detect_signal', lambda frame,*args: sig if len(frame)==1 else None)
    trades = run_backtest(df, fee_bps=10, slippage_bps=5, max_holding_bars=1)
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_time == df.index[1].isoformat()
    assert t.entry == pytest.approx(df.open.iloc[1]*1.0005)
    assert t.net_r == pytest.approx((t.exit-t.entry-0.001*(t.entry+t.exit))/(t.entry-t.stop))
    assert summarize(trades)['trades'] == 1


def test_config_example_loads():
    from app.config import load_config
    assert load_config('config/config.example.yml').history_bars == 250


def test_scanner_retries_only_failed_recipient(tmp_path, monkeypatch):
    from app import scanner
    from app.config import load_config
    cfg = load_config('config/config.example.yml')
    cfg.symbols = cfg.symbols[:1]
    df = _make_ohlc([100.]*160)
    sig = detect_signal(setup_frame(), 2)
    sig.bar_time = pd.Timestamp.now(tz='UTC')-pd.Timedelta(hours=1,seconds=10)
    monkeypatch.setattr(scanner, 'detect_signal', lambda *a,**kw:sig)
    source = Mock()
    source.fetch_ohlc.return_value = df
    notifier = Mock()
    notifier.chat_ids = ('a','b')
    notifier.send.side_effect = [{'a'},{'b'}]
    seen = SeenStore(str(tmp_path/'state.json'))
    for _ in range(3): scanner.scan_once(cfg, {'binance':source}, notifier, seen)
    assert notifier.send.call_count == 2
    assert notifier.send.call_args_list[1].kwargs['chat_ids'] == ['b']


@pytest.mark.parametrize('age,dry_run', [(-30,False),(10000,False),(10,True)])
def test_scanner_future_stale_and_dry_run(tmp_path, monkeypatch, age, dry_run):
    from app import scanner
    from app.config import load_config
    cfg = load_config('config/config.example.yml')
    cfg.symbols = cfg.symbols[:1]
    sig = detect_signal(setup_frame(), 2)
    sig.bar_time = pd.Timestamp.now(tz='UTC')-pd.Timedelta(hours=1,seconds=age)
    monkeypatch.setattr(scanner, 'detect_signal', lambda *a,**kw:sig)
    source = Mock()
    source.fetch_ohlc.return_value = _make_ohlc([100.]*160)
    notifier = Mock()
    state_file = tmp_path/'state.json'
    scanner.scan_once(cfg, {'binance':source}, notifier, SeenStore(str(state_file)), dry_run=dry_run)
    notifier.send.assert_not_called()
    if dry_run or age < 0: assert not state_file.exists()


def test_ichimoku_exact_values():
    df = _make_ohlc(list(range(100,200)))
    out = compute_ichimoku(df)
    assert out.tenkan.iloc[80] == (df.high.iloc[72:81].max()+df.low.iloc[72:81].min())/2
    assert out.kijun.iloc[80] == (df.high.iloc[55:81].max()+df.low.iloc[55:81].min())/2
    assert out.senkou_b.iloc[80] == (df.high.iloc[3:55].max()+df.low.iloc[3:55].min())/2
    assert out.senkou_a.iloc[80] == (out.tenkan.iloc[54]+out.kijun.iloc[54])/2


@pytest.mark.parametrize('options', [dict(min_breakout_atr=-1),dict(max_stop_pct=float('nan')),
                                    dict(require_projected_cloud='false')])
def test_invalid_strategy_options_rejected(options):
    with pytest.raises(ValueError): StrategyOptions(**options)


def test_backtest_respects_test_start(monkeypatch):
    from app import backtest
    df = _make_ohlc([82.,84.,86.,88.])
    sig = detect_signal(setup_frame(), 2)
    detector = Mock(return_value=sig)
    monkeypatch.setattr(backtest, 'detect_signal', detector)
    trades = run_backtest(df, signal_start=df.index[2], max_holding_bars=1)
    assert detector.call_count == 1
    assert trades[0].entry_time == df.index[3].isoformat()
