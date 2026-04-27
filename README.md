# Ichimoku Chikou Breakout Telegram Bot

A Telegram bot that scans your watchlist of forex and crypto symbols for a very specific Ichimoku setup — **Chikou Span breakout after a Tenkan-sen / Kijun-sen cross** — and sends you a formatted alert when one prints on the most recently closed bar.

No paid data feeds. No API keys beyond the Telegram bot token. Deploy with one `docker compose up -d`.

## The strategy, in one paragraph

The classical Ichimoku "T/K cross" on its own produces a lot of fakeouts, especially when the cross happens inside or against the Kumo. This bot only fires when **two** conditions are in sequence:

1. A Tenkan-sen / Kijun-sen cross occurs on the wrong side of the Kumo (bullish cross below the cloud for longs; bearish cross above it for shorts) — a momentum-shift hint, not an entry.
2. Within the next N bars, the **Chikou Span breaks past the price candles** at its own chart position (`close[t] > high[t-26]` for longs, or below `low[t-26]` for shorts). That is the entry bar.

The stop-loss is set to the tighter of the Kijun-sen or the swing since the qualifying cross. Only closed bars are ever evaluated.

## Project layout

```
ichimoku-bot/
├── app/
│   ├── main.py              # Poll loop + graceful shutdown
│   ├── config.py            # YAML loader with ${ENV} expansion
│   ├── scanner.py           # Orchestrates fetch → compute → detect → notify
│   ├── state.py             # Per-bar alert dedup (JSON in /data)
│   ├── strategies/
│   │   ├── ichimoku.py      # Tenkan, Kijun, Senkou A/B, Chikou, Kumo
│   │   └── signals.py       # Chikou-breakout-after-cross detector
│   ├── data_sources/
│   │   ├── binance_source.py   # Crypto, public REST, no auth
│   │   └── yahoo_source.py     # Forex/stocks/futures via yfinance, no auth
│   └── notifiers/
│       └── telegram.py      # Bot API sendMessage
├── config/config.yml        # Watchlist + Ichimoku + scan settings
├── tests/                   # Unit tests for the signal detector
├── scripts/smoke_binance.py # End-to-end smoke test against live data
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Prerequisites

- Docker and Docker Compose (v2 — `docker compose`, not `docker-compose`)
- A Telegram account

Nothing else. No broker account, no data-vendor signup.

## Quick start

### 1. Create the Telegram bot

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, follow the prompts, and save the **bot token** it gives you.
3. Open a chat with your new bot and send it any message (e.g. `/start`). This is required — bots cannot send you messages until you have messaged them at least once.
4. Open a chat with [@userinfobot](https://t.me/userinfobot) and send it any message. It will reply with your **numeric chat ID**.

### 2. Configure

```bash
git clone <your-repo-url> ichimoku-bot
cd ichimoku-bot
cp .env.example .env
```

Edit `.env` and fill in:

```
TELEGRAM_BOT_TOKEN=123456789:AAAA...
TELEGRAM_CHAT_IDS=123456789
LOG_LEVEL=INFO
```

`TELEGRAM_CHAT_IDS` accepts a comma-separated list if you want the bot to notify multiple people or groups.

Then edit `config/config.yml` to match your watchlist. The file ships with a sensible default (BTC, ETH, SOL on Binance and EUR/USD, GBP/USD, USD/JPY, AUD/USD on Yahoo).

### 3. Run it

```bash
docker compose up -d
docker compose logs -f
```

You should see a startup message in Telegram listing your watchlist, then a `"no signal"` log line for each symbol every `poll_interval_seconds`. When a setup prints on a closed bar, you'll get a formatted alert like:

```
🟢 LONG — BTC/USDT
Ichimoku Chikou Breakout (post T/K cross)

• Timeframe: 4h
• Source: binance
• Bar: 2026-04-21T12:00:00+00:00
• Entry: 71234.50
• Stop:  70010.00  (risk ≈ 1.72%)
• Tenkan: 70980  |  Kijun: 70420
• Kumo: 69500 → 70800
• Qualifying T/K cross: 2026-04-19T04:00:00+00:00

Targets: next S/R or opposite side of higher-TF Kumo. Trail with Kijun-sen.
```

### 4. Updating the watchlist

Edit `config/config.yml` and restart the service. The config is bind-mounted, so no rebuild is needed:

```bash
docker compose restart
```

## Symbol reference

| Market | Source    | Format                    | Example                |
|--------|-----------|---------------------------|------------------------|
| Crypto | `binance` | `<BASE><QUOTE>`           | `BTCUSDT`, `ETHUSDT`   |
| Crypto | `yahoo`   | `<BASE>-USD`              | `BTC-USD`, `ETH-USD`   |
| Forex  | `yahoo`   | `<PAIR>=X` or `A/B` or `ABCDEF` | `EURUSD=X`, `EUR/USD`, `EURUSD` |
| Futures | `yahoo`  | `<TICKER>=F`              | `GC=F` (gold), `CL=F` (WTI) |
| Equity | `yahoo`   | Yahoo ticker              | `AAPL`, `TSLA`         |

The Yahoo source auto-translates friendly forex forms — `"EUR/USD"` and `"EURUSD"` both become `EURUSD=X` under the hood.

## Supported timeframes

| Timeframe | Binance | Yahoo |
|-----------|---------|-------|
| `1m`      | ✅      | ✅ (last 7 days only) |
| `5m`      | ✅      | ✅ (last 60 days only) |
| `15m`     | ✅      | ✅ (last 60 days only) |
| `30m`     | ✅      | ✅ (last 60 days only) |
| `1h`      | ✅      | ✅ (last 60 days only) |
| `4h`      | ✅      | ❌ (use `1h` or `1d`)  |
| `1d`      | ✅      | ✅                    |
| `1w`      | ✅      | ✅                    |

The Yahoo intraday history limit is Yahoo's own, not ours. For Ichimoku you need ~100+ bars of history, which `1h` and above will always give you.

## Polling and rate limits

- **Binance**: the bot hits `api.binance.com/api/v3/klines`, which is rate-limited per IP but very generous (thousands of requests per minute). One request per symbol per poll is a rounding error.
- **Yahoo**: yfinance scrapes Yahoo's public chart endpoints. There is no officially published rate limit, but aggressive polling (< 1 minute) can get you temporarily throttled. The default `poll_interval_seconds: 300` is conservative.

## How alerts are deduplicated

The dedup key is `{source}:{symbol}:{timeframe}:{bar_time}:{side}`. Once an alert is sent for a given bar, it's written to `/data/seen_signals.json` (a Docker named volume), so restarts don't re-fire old alerts. If you want to force re-alerting (e.g. after tweaking the strategy), just delete that file:

```bash
docker compose down
docker volume rm ichimoku-bot_ichimoku-state
docker compose up -d
```

## Tuning knobs

All in `config/config.yml`:

| Setting | What it does |
|---|---|
| `ichimoku.tenkan / kijun / senkou_b / displacement` | Standard Ichimoku periods. Leave at 9/26/52/26 unless you know why. |
| `scan.cross_lookback_bars` | How far back to look for the qualifying T/K cross. 60 is comfortable. Lower it (e.g. 30) to only catch very recent crosses. |
| `scan.history_bars` | How many closed bars to fetch per scan. Must exceed `senkou_b + displacement` by a healthy margin. 200 is safe. |
| `scan.poll_interval_seconds` | How often to re-scan the whole watchlist. For a 1d timeframe, 1800 or 3600 is plenty. For 1h, 300 is typical. |

## Running the tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

The test suite builds a synthetic downtrend → base → rally series that is textbook for the strategy, and asserts that `detect_signal()` fires a long on the breakout bar.

There is also a smoke test that calls the real Binance API:

```bash
python scripts/smoke_binance.py
```

## Caveats

- **This bot does not trade.** It sends alerts. Hooking it up to a broker is deliberately out of scope — that's a very different risk surface.
- **Signal ≠ guaranteed win.** Ichimoku is a trend-following framework; in range-bound markets this setup will chop. The video's own advice applies: skip the setup when the Chikou is stuck sideways inside past price.
- **Yahoo forex data is delayed** (usually a few minutes on intraday, end-of-day on `1d`). This is fine for 1h and higher timeframes but don't expect tick-level precision.
- **Timezone**: all timestamps are UTC internally. Set `TZ` in `.env` (defaults to `Europe/Madrid`) if you want log lines in a specific local time.

## License

MIT.
