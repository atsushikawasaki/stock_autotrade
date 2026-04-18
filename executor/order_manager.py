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
    place_stop_sell,
    place_trailing_stop_sell,
    place_take_profit_sell,
    wait_for_fill,
    cancel_order,
    cancel_orders,
    OrderResult,
)
import notifier
import risk_manager
from constants import (
    CLAUDE_ENABLED,
    MIN_TRADE_GRADE,
    MAX_ENTRY_PRICE_DEVIATION_PCT,
    SERVER_SIDE_EXITS_ENABLED,
    TRAILING_STOP_PCT,
)
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


def calc_position_size(
    entry_price: float,
    balance: float | None,
    atr: float | None = None,
) -> int:
    """Calculate number of shares based on max position % of account,
    adjusted for volatility (ATR-based sizing).

    Higher volatility -> smaller position to normalize risk across holdings.
    """
    if balance is None or balance <= 0:
        return 0
    max_dollar = balance * (MAX_POSITION_PCT / 100)

    # Volatility adjustment: scale down position for high-ATR stocks
    if atr is not None and atr > 0 and entry_price > 0:
        volatility_pct = (atr / entry_price) * 100  # daily volatility as %
        # Target ~1.5% daily vol per position; scale inversely above that
        target_vol_pct = 1.5
        if volatility_pct > target_vol_pct:
            vol_scale = target_vol_pct / volatility_pct
            max_dollar *= vol_scale

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
    # Extract ATR from signal indicators for volatility-adjusted sizing
    indicators = signal.get("indicators") or {}
    atr = indicators.get("atr")
    if atr is not None:
        atr = float(atr)

    qty = calc_position_size(entry_price, balance, atr=atr)
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

    # Place server-side exit orders (SL + trailing stop)
    exit_order_ids = [result.order_id]
    sl_price = signal.get("stop_loss")
    tp_price = signal.get("take_profit")

    if SERVER_SIDE_EXITS_ENABLED:
        exit_order_ids = _place_exit_orders(
            stock_code, fill_qty, fill_price, sl_price, tp_price, exit_order_ids,
        )

    # Create position record with actual fill price
    sb.table("us_positions").insert({
        "signal_id": signal_id,
        "stock_code": stock_code,
        "entry_price": fill_price,
        "quantity": fill_qty,
        "stop_loss": sl_price,
        "take_profit": tp_price,
        "status": "open",
        "moomoo_order_ids": exit_order_ids,
    }).execute()

    print(f"[BUY] {stock_code} x{fill_qty} @ ${fill_price:.2f} (order: {result.order_id})")
    notifier.notify_order_executed(
        stock_code, signal.get("strategy", ""), fill_qty, fill_price, result.order_id or "",
    )
    return True


def _place_exit_orders(
    stock_code: str,
    qty: int,
    entry_price: float,
    sl_price: float | None,
    tp_price: float | None,
    order_ids: list[str],
) -> list[str]:
    """Place server-side SL and trailing stop orders after entry fill.

    Strategy:
    - STOP order at SL price as safety net (hard floor)
    - TRAILING_STOP to lock in profits as price rises
    - No fixed TP — trailing stop replaces it for better upside capture

    Returns updated list of order IDs.
    """
    ids = list(order_ids)

    # 1. Stop-loss order (hard floor)
    if sl_price is not None:
        sl_result = place_stop_sell(stock_code, qty, float(sl_price))
        if sl_result.success:
            ids.append(sl_result.order_id)
            print(f"  [SL] {stock_code} stop @ ${float(sl_price):.2f} (order: {sl_result.order_id})")
        else:
            print(f"  [SL] {stock_code} stop order failed: {sl_result.message}")

    # 2. Trailing stop (profit lock — replaces fixed TP)
    trail_result = place_trailing_stop_sell(stock_code, qty, TRAILING_STOP_PCT)
    if trail_result.success:
        ids.append(trail_result.order_id)
        print(f"  [TRAIL] {stock_code} trailing {TRAILING_STOP_PCT}% (order: {trail_result.order_id})")
    else:
        # Fallback: use fixed TP if trailing stop not supported
        print(f"  [TRAIL] {stock_code} trailing failed: {trail_result.message}")
        if tp_price is not None:
            tp_result = place_take_profit_sell(stock_code, qty, float(tp_price))
            if tp_result.success:
                ids.append(tp_result.order_id)
                print(f"  [TP] {stock_code} take-profit @ ${float(tp_price):.2f} (order: {tp_result.order_id})")

    return ids


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

    # Cancel remaining server-side exit orders to prevent double-sell
    # (Not needed for server_side_exit — that order already filled)
    if exit_reason != "server_side_exit" and SERVER_SIDE_EXITS_ENABLED:
        order_ids = position.get("moomoo_order_ids") or []
        if len(order_ids) > 1:
            exit_ids = order_ids[1:]
            cancelled = cancel_orders(exit_ids)
            if cancelled > 0:
                print(f"  [CANCEL] {stock_code}: cancelled {cancelled}/{len(exit_ids)} exit orders before {exit_reason}")

    # Server-side exit: moomoo already filled the order — skip placing a new sell
    if exit_reason == "server_side_exit":
        actual_exit_price = exit_price  # already the fill price from moomoo
        actual_qty = qty
        sell_order_id = None
    else:
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

        # Wait for fill confirmation
        fill = wait_for_fill(result.order_id, timeout_seconds=30)
        if not fill.filled:
            print(f"[NOFILL] {stock_code} sell order {result.order_id} not filled: {fill.message}")
            _exit_fail_cooldown[position_id] = time.time() + _EXIT_COOLDOWN_SECONDS
            return False

        actual_exit_price = fill.dealt_avg_price if fill.dealt_avg_price > 0 else exit_price
        actual_qty = fill.dealt_qty if fill.dealt_qty > 0 else qty
        sell_order_id = result.order_id

    now = datetime.now(timezone.utc)
    entry_price = float(position["entry_price"])
    return_pct = round(((actual_exit_price - entry_price) / entry_price) * 100, 2)
    opened_at = datetime.fromisoformat(position["opened_at"].replace("Z", "+00:00"))
    holding_days = (now - opened_at).days

    # Update position
    order_ids = list(position.get("moomoo_order_ids") or [])
    if sell_order_id is not None:
        order_ids.append(sell_order_id)

    sb.table("us_positions").update({
        "status": "closed",
        "closed_at": now.isoformat(),
        "moomoo_order_ids": order_ids,
    }).eq("id", position_id).execute()

    # Record outcome with actual fill price
    sb.table("us_signal_outcomes").insert({
        "signal_id": signal_id,
        "position_id": position_id,
        "exit_date": now.strftime("%Y-%m-%d"),
        "exit_price": actual_exit_price,
        "exit_reason": exit_reason,
        "return_pct": return_pct,
        "holding_days": holding_days,
    }).execute()

    pnl = (actual_exit_price - entry_price) * actual_qty
    emoji = "+" if return_pct >= 0 else ""
    print(f"[SELL] {stock_code} x{actual_qty} @ ${actual_exit_price:.2f} ({exit_reason}) {emoji}{return_pct}%")
    notifier.notify_exit(stock_code, exit_reason, entry_price, actual_exit_price, actual_qty, pnl)
    return True
