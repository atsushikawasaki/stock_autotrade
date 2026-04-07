#!/usr/bin/env python3
"""
US Stock Auto-Trade Executor

Main loop that:
1. Polls Supabase for pending signals → executes buy orders via moomoo
2. Monitors open positions → executes exits (SL/TP/time expiry)

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

from config import POLL_INTERVAL_SECONDS, MOOMOO_TRADE_PWD
from moomoo_client import unlock_trade, get_account_balance
from order_manager import (
    fetch_pending_signals,
    fetch_open_positions,
    execute_signal,
    execute_exit,
)
from position_monitor import get_current_price, determine_exit


def is_market_open() -> bool:
    """Check if US market is currently open (rough check)."""
    now = datetime.now(timezone.utc)
    # NYSE: Mon-Fri, 14:30-21:00 UTC (9:30 AM - 4:00 PM ET)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    hour_min = now.hour * 100 + now.minute
    return 1430 <= hour_min < 2100


def process_pending_signals() -> int:
    """Process all pending buy signals. Returns count of executed."""
    signals = fetch_pending_signals()
    if not signals:
        return 0

    executed = 0
    for signal in signals:
        try:
            if execute_signal(signal):
                executed += 1
        except Exception as e:
            print(f"[ERROR] Signal execution failed for {signal.get('stock_code')}: {e}")
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
            print(f"[ERROR] Position monitor failed for {pos.get('stock_code')}: {e}")
            traceback.print_exc()

    return exited


def main():
    print("=" * 60)
    print("US Stock Auto-Trade Executor")
    print(f"  Poll interval: {POLL_INTERVAL_SECONDS}s")
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
        print(f"[INFO] Account buying power: ${balance:,.2f}")
    else:
        print("[WARN] Could not fetch account balance")

    print("\n[START] Entering main loop...\n")

    while True:
        try:
            now = datetime.now(timezone.utc)
            market_open = is_market_open()

            if market_open:
                # Execute pending signals
                n_executed = process_pending_signals()
                if n_executed > 0:
                    print(f"[{now.strftime('%H:%M:%S')}] Executed {n_executed} signal(s)")

                # Monitor positions
                n_exited = monitor_positions()
                if n_exited > 0:
                    print(f"[{now.strftime('%H:%M:%S')}] Exited {n_exited} position(s)")
            else:
                # Market closed: still check for pending signals (queue for next open)
                # but don't execute or monitor
                pass

        except KeyboardInterrupt:
            print("\n[STOP] Executor stopped by user")
            break
        except Exception as e:
            print(f"[ERROR] Main loop error: {e}")
            traceback.print_exc()

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
