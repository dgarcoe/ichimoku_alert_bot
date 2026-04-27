"""Entrypoint: poll, scan, notify, repeat."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from threading import Event

from .config import load_config
from .notifiers import TelegramNotifier
from .scanner import build_sources, scan_once
from .state import SeenStore


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    _configure_logging()
    log = logging.getLogger("ichimoku-bot")

    parser = argparse.ArgumentParser(description="Ichimoku Chikou Breakout Telegram bot")
    parser.add_argument(
        "--config",
        default=os.environ.get("CONFIG_PATH", "/app/config/config.yml"),
        help="Path to YAML config (default: /app/config/config.yml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit (useful for debugging)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    log.info(
        "Loaded config: %d symbol(s), poll=%ds, state=%s",
        len(cfg.symbols), cfg.poll_interval_seconds, cfg.state_path,
    )

    if not cfg.telegram_bot_token or not cfg.telegram_chat_ids:
        log.error("Telegram bot_token and at least one chat_id are required.")
        return 2
    if not cfg.symbols:
        log.error("No symbols configured; nothing to do.")
        return 2

    notifier = TelegramNotifier(
        bot_token=cfg.telegram_bot_token,
        chat_ids=cfg.telegram_chat_ids,
    )
    sources = build_sources(cfg)
    seen = SeenStore(cfg.state_path)

    stop = Event()

    def _handle_signal(signum, _frame):
        log.info("Received signal %s; shutting down.", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if cfg.startup_message:
        symbol_lines = "\n".join(
            f"• {s.display} ({s.source}, {s.timeframe})" for s in cfg.symbols
        )
        notifier.send(
            "<b>🔔 Ichimoku bot is up</b>\n"
            f"Polling every {cfg.poll_interval_seconds}s\n\n"
            f"<b>Watchlist:</b>\n{symbol_lines}"
        )

    while not stop.is_set():
        started = time.monotonic()
        try:
            scan_once(cfg, sources, notifier, seen)
        except Exception as exc:  # noqa: BLE001
            log.exception("Unhandled scan error: %s", exc)

        if args.once:
            break

        elapsed = time.monotonic() - started
        wait = max(1.0, cfg.poll_interval_seconds - elapsed)
        stop.wait(wait)

    log.info("Bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
