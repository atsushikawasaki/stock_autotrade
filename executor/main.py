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

import sys
import time
import traceback
from datetime import datetime, timezone

from supabase import create_client

from config import (
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    POLL_INTERVAL_SECONDS,
    MOOMOO_TRADE_PWD,
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
from constants import NOTIFY_GRADES

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

SCAN_INTERVAL_SECONDS = 300  # Signal scan every 5 min during market hours


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

        except Exception as e:
            print(f"  [ERR] {code}: {e}")

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
    print("=" * 60)
    print("US Stock Auto-Trade Executor (All-in-One)")
    print(f"  Poll interval: {POLL_INTERVAL_SECONDS}s")
    print(f"  Scan interval: {SCAN_INTERVAL_SECONDS}s")
    print(f"  Trade password: {'set' if MOOMOO_TRADE_PWD else 'NOT SET'}")
    print("=" * 60)

    # Unlock trading
    if MOOMOO_TRADE_PWD:
        if not unlock_trade():
            print("[FATAL] Failed to unlock trading. Exiting.")
            sys.exit(1)

    # Show account balance
    balance = get_account_balance()
    if balance is not None:
        print(f"[INFO] Buying power: ${balance:,.2f}")
    else:
        print("[WARN] Could not fetch account balance")

    print("\n[START] Entering main loop...\n")

    last_scan = 0.0

    while True:
        try:
            now = time.time()
            market_open = is_market_open()
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

            if market_open:
                # Signal scan (every SCAN_INTERVAL_SECONDS)
                if now - last_scan >= SCAN_INTERVAL_SECONDS:
                    scan_signals()
                    last_scan = now

                # Execute pending signals
                n_exec = process_pending_signals()
                if n_exec > 0:
                    print(f"[{ts}] Executed {n_exec} signal(s)")

                # Monitor positions
                n_exit = monitor_positions()
                if n_exit > 0:
                    print(f"[{ts}] Exited {n_exit} position(s)")
            else:
                # Market closed — run one scan after close for end-of-day signals
                if now - last_scan >= 3600:
                    utc_hour = datetime.now(timezone.utc).hour
                    # Scan once after market close (21:00-22:00 UTC)
                    if 21 <= utc_hour <= 22:
                        print(f"[{ts}] Post-market scan...")
                        scan_signals()
                        last_scan = now

        except KeyboardInterrupt:
            print("\n[STOP] Executor stopped by user")
            break
        except Exception as e:
            print(f"[ERR] Main loop: {e}")
            traceback.print_exc()

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
