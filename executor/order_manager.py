"""Order management: position sizing, signal execution, and exit handling."""

from __future__ import annotations

import math
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
    OrderResult,
)
import notifier
import risk_manager

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


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


def execute_signal(signal: dict) -> bool:
    """Execute a pending buy signal via moomoo."""
    stock_code = signal["stock_code"]
    entry_price = float(signal["entry_price"])
    signal_id = signal["id"]

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

    # Place buy order
    result = place_limit_buy(stock_code, entry_price, qty)
    if not result.success:
        print(f"[FAIL] {stock_code} buy order failed: {result.message}")
        notifier.notify_order_failed(stock_code, signal.get("strategy", ""), result.message)
        return False

    now = datetime.now(timezone.utc).isoformat()

    # Update signal status
    sb.table("us_signals").update({
        "status": "executed",
        "executed_price": entry_price,
        "executed_qty": qty,
        "executed_at": now,
        "moomoo_order_id": result.order_id,
    }).eq("id", signal_id).execute()

    # Create position record
    sb.table("us_positions").insert({
        "signal_id": signal_id,
        "stock_code": stock_code,
        "entry_price": entry_price,
        "quantity": qty,
        "stop_loss": signal.get("stop_loss"),
        "take_profit": signal.get("take_profit"),
        "status": "open",
        "moomoo_order_ids": [result.order_id],
    }).execute()

    print(f"[BUY] {stock_code} x{qty} @ ${entry_price:.2f} (order: {result.order_id})")
    notifier.notify_order_executed(
        stock_code, signal.get("strategy", ""), qty, entry_price, result.order_id or "",
    )
    return True


def execute_exit(position: dict, exit_reason: str, exit_price: float) -> bool:
    """Execute an exit (sell) for an open position."""
    stock_code = position["stock_code"]
    qty = int(position["quantity"])
    position_id = position["id"]
    signal_id = position["signal_id"]

    # Place sell order
    if exit_reason in ("stop_loss", "time_expiry"):
        result = place_market_sell(stock_code, qty)
    else:
        result = place_limit_sell(stock_code, exit_price, qty)

    if not result.success:
        print(f"[FAIL] {stock_code} sell failed: {result.message}")
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
