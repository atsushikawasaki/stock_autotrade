#!/usr/bin/env python3
"""
US Stock Auto-Trade Executor (All-in-One)

Single daemon that handles everything:
1. Fetches prices from Yahoo Finance
2. Runs Strategy A/B/C signal detection
3. Saves signals to Supabase
4. Executes buy orders via moomoo OpenAPI
5. Monitors positions and executes exits

Requires:
- moomoo OpenD running on localhost:11111
- Environment variables in .env (see .env.example)

Usage:
  cd executor
  pip install -r requirements.txt
  python main.py
"""

import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from supabase import create_client

from config import (
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    POLL_INTERVAL_SECONDS,
    MOOMOO_TRADE_PWD,
    TRADE_ENV,
)
from moomoo_client import unlock_trade, get_account_balance
from order_manager import (
    fetch_pending_signals,
    fetch_open_positions,
    execute_signal,
    execute_exit,
)
from position_monitor import get_current_price, determine_exit
from price_client import fetch_daily_prices
from strategies import evaluate_all_strategies
from market_filter import get_market_regime
from constants import NOTIFY_GRADES, CLAUDE_REVIEW_ENABLED
from daily_reviewer import generate_daily_review
from backtest_worker import poll_and_run as poll_backtest_queue
import notifier

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

SCAN_INTERVAL_SECONDS = 300  # Signal scan every 5 min during market hours
HEARTBEAT_INTERVAL_SECONDS = 300  # Health check every 5 min

log = logging.getLogger("executor")


LOG_RETENTION_DAYS = 14


def setup_logging() -> None:
    """Configure logging to stdout + file, and clean up old logs."""
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"executor_{datetime.now().strftime('%Y%m%d')}.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    _cleanup_old_logs(log_dir)


def _cleanup_old_logs(log_dir: Path) -> None:
    """Delete log files older than LOG_RETENTION_DAYS."""
    import os
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    for f in log_dir.glob("executor_*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def write_heartbeat() -> None:
    """Write a heartbeat record to Supabase for health monitoring."""
    try:
        sb.table("us_executor_heartbeat").upsert({
            "id": "main",
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }, on_conflict="id").execute()
    except Exception as e:
        log.warning("Heartbeat write failed: %s", e)


def is_market_open() -> bool:
    """Check if US market is currently open (rough check)."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    hour_min = now.hour * 100 + now.minute
    return 1430 <= hour_min < 2100


def fetch_active_stocks() -> list[dict]:
    """Fetch all active US stocks from Supabase."""
    result = sb.table("us_stocks").select("*").eq("is_active", True).order("code").execute()
    return result.data or []


def scan_signals() -> int:
    """
    Run signal detection on all active stocks.
    Returns count of new signals found.
    """
    stocks = fetch_active_stocks()
    if not stocks:
        print("[SCAN] No active stocks")
        return 0

    market_regime = get_market_regime()
    print(f"[SCAN] Scanning {len(stocks)} stocks (regime: {market_regime})")

    signals_found = 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for stock in stocks:
        code = stock["code"]
        try:
            prices = fetch_daily_prices(code, 120)
            if len(prices) < 80:
                continue

            signals = evaluate_all_strategies(prices, market_regime)

            for sig in signals:
                if not sig.triggered:
                    continue

                # Upsert signal
                row = {
                    "stock_code": code,
                    "signal_date": today,
                    "strategy": sig.strategy,
                    "direction": "buy",
                    "score": sig.score,
                    "grade": sig.grade,
                    "entry_price": sig.entry_price,
                    "stop_loss": sig.stop_loss,
                    "take_profit": sig.take_profit,
                    "indicators": sig.indicators,
                    "reason": sig.reason,
                    "status": "pending",
                }

                sb.table("us_signals").upsert(
                    row,
                    on_conflict="stock_code,signal_date,strategy",
                ).execute()

                signals_found += 1
                label = sig.strategy.replace("strategy_", "").upper()
                print(
                    f"  [{sig.grade}] {code} Strategy {label} "
                    f"score:{sig.score} entry:${sig.entry_price:.2f} "
                    f"SL:${sig.stop_loss:.2f if sig.stop_loss else 0} "
                    f"TP:${sig.take_profit:.2f if sig.take_profit else 0}"
                )

                if sig.grade in NOTIFY_GRADES:
                    notifier.buffer_signal(
                        code, sig.strategy, sig.grade, sig.score,
                        sig.entry_price, sig.stop_loss, sig.take_profit, sig.reason,
                    )

        except Exception as e:
            print(f"  [ERR] {code}: {e}")

    # Send all buffered signals as one LINE message
    notifier.flush_signals()

    print(f"[SCAN] Done — {signals_found} signal(s) found")
    return signals_found


def process_pending_signals() -> int:
    """Execute all pending buy signals. Returns count of executed."""
    signals = fetch_pending_signals()
    if not signals:
        return 0

    executed = 0
    for signal in signals:
        try:
            if execute_signal(signal):
                executed += 1
        except Exception as e:
            print(f"[ERR] Signal exec failed for {signal.get('stock_code')}: {e}")
            traceback.print_exc()

    return executed


def monitor_positions() -> int:
    """Check all open positions for exit conditions. Returns count of exits."""
    positions = fetch_open_positions()
    if not positions:
        return 0

    exited = 0
    for pos in positions:
        try:
            current = get_current_price(pos["stock_code"])
            if current is None:
                continue

            result = determine_exit(pos, current)
            if result is not None:
                exit_reason, exit_price = result
                if execute_exit(pos, exit_reason, exit_price):
                    exited += 1
        except Exception as e:
            print(f"[ERR] Position monitor failed for {pos.get('stock_code')}: {e}")
            traceback.print_exc()

    return exited


def main():
    setup_logging()

    log.info("=" * 60)
    log.info("US Stock Auto-Trade Executor (All-in-One)")
    log.info("  Poll interval: %ds", POLL_INTERVAL_SECONDS)
    log.info("  Scan interval: %ds", SCAN_INTERVAL_SECONDS)
    log.info("  Trade env: %s", TRADE_ENV)
    log.info("  Trade password: %s", "set" if MOOMOO_TRADE_PWD else "NOT SET")
    log.info("=" * 60)

    # Unlock trading
    # Note: moomoo OpenD GUI version has the unlock_trade API disabled — the
    # user must unlock from the OpenD GUI once per session. Unlock failure is
    # only a warning here so the daemon keeps running (scans, heartbeat, and
    # position monitoring all work without trade unlock). Order placement will
    # fail until the user unlocks from the GUI.
    if TRADE_ENV == "SIMULATE":
        log.info("SIMULATE mode — skipping trade unlock")
    elif MOOMOO_TRADE_PWD:
        if not unlock_trade():
            log.warning(
                "API unlock failed — please unlock from moomoo OpenD GUI. "
                "Scans and monitoring will continue; order placement may fail."
            )

    # Show account balance
    balance = get_account_balance()
    if balance is not None:
        log.info("Buying power: $%s", f"{balance:,.2f}")
    else:
        log.warning("Could not fetch account balance")

    log.info("Entering main loop...")

    last_scan = 0.0
    last_heartbeat = 0.0
    daily_review_done = ""  # date string to prevent duplicate reviews

    while True:
        try:
            now = time.time()
            market_open = is_market_open()

            # Heartbeat
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                write_heartbeat()
                last_heartbeat = now

            # Backtest queue (always, regardless of market hours)
            try:
                if poll_backtest_queue():
                    log.info("Backtest request processed")
            except Exception as e:
                log.warning("Backtest queue error: %s", e)

            if market_open:
                # Signal scan (every SCAN_INTERVAL_SECONDS)
                if now - last_scan >= SCAN_INTERVAL_SECONDS:
                    scan_signals()
                    last_scan = now

                # Execute pending signals
                n_exec = process_pending_signals()
                if n_exec > 0:
                    log.info("Executed %d signal(s)", n_exec)

                # Monitor positions
                n_exit = monitor_positions()
                if n_exit > 0:
                    log.info("Exited %d position(s)", n_exit)
            else:
                # Market closed — run one scan after close for end-of-day signals
                if now - last_scan >= 3600:
                    utc_hour = datetime.now(timezone.utc).hour
                    # Scan once after market close (21:00-22:00 UTC)
                    if 21 <= utc_hour <= 22:
                        log.info("Post-market scan...")
                        scan_signals()
                        last_scan = now

                        # Daily AI review (once per day)
                        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        if CLAUDE_REVIEW_ENABLED and daily_review_done != today_str:
                            review = generate_daily_review()
                            if review:
                                notifier.notify_daily_review(review)
                            daily_review_done = today_str

        except KeyboardInterrupt:
            log.info("Executor stopped by user")
            break
        except Exception as e:
            log.error("Main loop error: %s", e, exc_info=True)
            notifier.notify_error("Main loop", str(e))

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
