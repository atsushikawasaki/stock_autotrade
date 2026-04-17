"""Order management: position sizing, signal execution, and exit handling."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from supabase import create_client

from config import (
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    MAX_POSITION_PCT,
    MAX_POSITIONS,
)
from moomoo_client import (
    get_account_balance,
    place_limit_buy,
    place_limit_sell,
    place_market_sell,
    wait_for_fill,
    cancel_order,
    OrderResult,
)
import notifier
import risk_manager
from constants import CLAUDE_ENABLED, MIN_TRADE_GRADE, MAX_ENTRY_PRICE_DEVIATION_PCT
from claude_validator import validate_entry
from price_client import fetch_current_price

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Track exit failures to avoid spamming the same error every poll cycle
_exit_fail_cooldown: dict[str, float] = {}  # position_id -> next_retry_timestamp
_EXIT_COOLDOWN_SECONDS = 300  # 5 min between retries


def fetch_pending_signals() -> list[dict]:
    """Fetch signals with status='pending' from Supabase."""
    result = (
        sb.table("us_signals")
        .select("*")
        .eq("status", "pending")
        .order("score", desc=True)
        .execute()
    )
    return result.data or []


def fetch_open_positions() -> list[dict]:
    """Fetch positions with status='open' or 'partial_closed'."""
    result = (
        sb.table("us_positions")
        .select("*, us_signals(*)")
        .in_("status", ["open", "partial_closed"])
        .execute()
    )
    return result.data or []


def count_open_positions() -> int:
    """Count currently open positions."""
    result = (
        sb.table("us_positions")
        .select("id", count="exact")
        .in_("status", ["open", "partial_closed"])
        .execute()
    )
    return result.count or 0


def calc_position_size(entry_price: float, balance: float | None) -> int:
    """Calculate number of shares based on max position % of account."""
    if balance is None or balance <= 0:
        return 0
    max_dollar = balance * (MAX_POSITION_PCT / 100)
    shares = math.floor(max_dollar / entry_price)
    return max(shares, 1) if shares > 0 else 0


_GRADE_RANK = {"A": 1, "B": 2, "C": 3, "D": 4}


def execute_signal(signal: dict) -> bool:
    """Execute a pending buy signal via moomoo."""
    stock_code = signal["stock_code"]
    entry_price = float(signal["entry_price"])
    signal_id = signal["id"]
    grade = signal.get("grade", "D")

    # Grade filter — reject signals below MIN_TRADE_GRADE
    if _GRADE_RANK.get(grade, 99) > _GRADE_RANK.get(MIN_TRADE_GRADE, 1):
        print(f"[SKIP] {stock_code}: grade {grade} below minimum {MIN_TRADE_GRADE}")
        sb.table("us_signals").update({"status": "cancelled"}).eq("id", signal_id).execute()
        return False

    # Claude AI entry validation gate
    if CLAUDE_ENABLED:
        result = validate_entry(signal)
        if not result.approved:
            print(f"[CLAUDE] {stock_code} rejected: {result.reasoning}")
            sb.table("us_signals").update({
                "status": "cancelled",
                "reason": f"[AI rejected] {result.reasoning}",
            }).eq("id", signal_id).execute()
            return False

    # Position sizing
    balance = get_account_balance()

    # Risk checks (position limit, daily loss, sector concentration)
    risk = risk_manager.check_all(stock_code, balance or 0)
    if not risk.allowed:
        print(f"[RISK] {stock_code}: {risk.reason}")
        sb.table("us_signals").update({"status": "cancelled"}).eq("id", signal_id).execute()
        return False
    qty = calc_position_size(entry_price, balance)
    if qty <= 0:
        print(f"[SKIP] {stock_code}: insufficient balance (${balance})")
        sb.table("us_signals").update({"status": "cancelled"}).eq("id", signal_id).execute()
        return False

    # Price deviation check — reject if entry price is too far from market
    market_price = fetch_current_price(stock_code)
    if market_price is not None:
        deviation_pct = abs(entry_price - market_price) / market_price * 100
        if deviation_pct > MAX_ENTRY_PRICE_DEVIATION_PCT:
            msg = (
                f"Entry ${entry_price:.2f} deviates {deviation_pct:.1f}% "
                f"from market ${market_price:.2f} (max {MAX_ENTRY_PRICE_DEVIATION_PCT}%)"
            )
            print(f"[PRICE] {stock_code}: {msg}")
            sb.table("us_signals").update({
                "status": "failed",
                "reason": f"Price deviation: {msg}",
            }).eq("id", signal_id).execute()
            return False

    # Place buy order
    result = place_limit_buy(stock_code, entry_price, qty)
    if not result.success:
        print(f"[FAIL] {stock_code} buy order failed: {result.message}")
        sb.table("us_signals").update({
            "status": "failed",
            "reason": f"Order failed: {result.message}",
        }).eq("id", signal_id).execute()
        notifier.notify_order_failed(stock_code, signal.get("strategy", ""), result.message)
        return False

    # Wait for fill confirmation
    fill = wait_for_fill(result.order_id, timeout_seconds=30)
    if not fill.filled:
        print(f"[NOFILL] {stock_code} order {result.order_id} not filled: {fill.message}")
        sb.table("us_signals").update({
            "status": "failed",
            "reason": f"Not filled: {fill.message}",
            "moomoo_order_id": result.order_id,
        }).eq("id", signal_id).execute()
        return False

    # Use actual fill price and quantity
    fill_price = fill.dealt_avg_price if fill.dealt_avg_price > 0 else entry_price
    fill_qty = fill.dealt_qty if fill.dealt_qty > 0 else qty
    now = datetime.now(timezone.utc).isoformat()

    # Update signal status
    sb.table("us_signals").update({
        "status": "executed",
        "executed_price": fill_price,
        "executed_qty": fill_qty,
        "executed_at": now,
        "moomoo_order_id": result.order_id,
    }).eq("id", signal_id).execute()

    # Create position record with actual fill price
    sb.table("us_positions").insert({
        "signal_id": signal_id,
        "stock_code": stock_code,
        "entry_price": fill_price,
        "quantity": fill_qty,
        "stop_loss": signal.get("stop_loss"),
        "take_profit": signal.get("take_profit"),
        "status": "open",
        "moomoo_order_ids": [result.order_id],
    }).execute()

    print(f"[BUY] {stock_code} x{fill_qty} @ ${fill_price:.2f} (order: {result.order_id})")
    notifier.notify_order_executed(
        stock_code, signal.get("strategy", ""), fill_qty, fill_price, result.order_id or "",
    )
    return True


def execute_exit(position: dict, exit_reason: str, exit_price: float) -> bool:
    """Execute an exit (sell) for an open position."""
    stock_code = position["stock_code"]
    qty = int(position["quantity"])
    position_id = position["id"]
    signal_id = position["signal_id"]

    # Skip if in cooldown from a recent failure
    cooldown_until = _exit_fail_cooldown.get(position_id, 0)
    if time.time() < cooldown_until:
        return False

    # Place sell order
    if exit_reason in ("stop_loss", "time_expiry"):
        result = place_market_sell(stock_code, qty)
    else:
        result = place_limit_sell(stock_code, exit_price, qty)

    if not result.success:
        print(f"[FAIL] {stock_code} sell failed: {result.message}")
        _exit_fail_cooldown[position_id] = time.time() + _EXIT_COOLDOWN_SECONDS
        notifier.notify_order_failed(stock_code, "exit", result.message)
        return False

    now = datetime.now(timezone.utc)
    entry_price = float(position["entry_price"])
    return_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
    opened_at = datetime.fromisoformat(position["opened_at"].replace("Z", "+00:00"))
    holding_days = (now - opened_at).days

    # Update position
    order_ids = position.get("moomoo_order_ids") or []
    order_ids.append(result.order_id)

    sb.table("us_positions").update({
        "status": "closed",
        "closed_at": now.isoformat(),
        "moomoo_order_ids": order_ids,
    }).eq("id", position_id).execute()

    # Record outcome
    sb.table("us_signal_outcomes").insert({
        "signal_id": signal_id,
        "position_id": position_id,
        "exit_date": now.strftime("%Y-%m-%d"),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "return_pct": return_pct,
        "holding_days": holding_days,
    }).execute()

    pnl = (exit_price - entry_price) * qty
    emoji = "+" if return_pct >= 0 else ""
    print(f"[SELL] {stock_code} x{qty} @ ${exit_price:.2f} ({exit_reason}) {emoji}{return_pct}%")
    notifier.notify_exit(stock_code, exit_reason, entry_price, exit_price, qty, pnl)
    return True
