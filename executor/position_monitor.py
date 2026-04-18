"""Position monitoring: checks exit conditions for open positions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from price_client import fetch_current_price
from constants import (
    CLAUDE_EXIT_ENABLED,
    MAX_HOLDING_DAYS_A,
    MAX_HOLDING_DAYS_B,
    MAX_HOLDING_DAYS_C,
    MAX_HOLDING_DAYS_D,
    SERVER_SIDE_EXITS_ENABLED,
)
from claude_validator import advise_exit
from moomoo_client import query_order_fill, cancel_orders, cancel_order, place_stop_sell

log = logging.getLogger("position_monitor")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def get_current_price(symbol: str) -> float | None:
    """Get current price via moomoo OpenAPI."""
    return fetch_current_price(symbol)


def check_stop_loss(position: dict, current_price: float) -> bool:
    sl = position.get("stop_loss")
    if sl is None:
        return False
    return current_price <= float(sl)


def check_take_profit(position: dict, current_price: float) -> bool:
    tp = position.get("take_profit")
    if tp is None:
        return False
    return current_price >= float(tp)


def check_time_expiry(position: dict, max_days: int = 30) -> bool:
    opened_at = position.get("opened_at")
    if not opened_at:
        return False
    opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - opened).days >= max_days


def check_server_side_fills(position: dict) -> tuple[str, float] | None:
    """Check if any server-side exit order (SL/trailing) has been filled on moomoo.

    Returns (exit_reason, fill_price) if a fill is detected, else None.
    """
    order_ids = position.get("moomoo_order_ids") or []
    if len(order_ids) <= 1:
        # Only the buy order ID — no exit orders placed
        return None

    # Check exit order IDs (skip index 0 which is the buy order)
    for oid in order_ids[1:]:
        try:
            fill = query_order_fill(oid)
            if fill.filled:
                log.info(
                    "[SERVER-EXIT] %s order %s filled: %d @ $%.2f",
                    position.get("stock_code"), oid, fill.dealt_qty, fill.dealt_avg_price,
                )
                return ("server_side_exit", fill.dealt_avg_price)
        except Exception as e:
            log.warning("Failed to check order %s: %s", oid, e)

    return None


def cancel_exit_orders(position: dict) -> None:
    """Cancel all server-side exit orders for a position (before manual exit)."""
    order_ids = position.get("moomoo_order_ids") or []
    if len(order_ids) <= 1:
        return
    exit_ids = order_ids[1:]
    cancelled = cancel_orders(exit_ids)
    if cancelled > 0:
        log.info(
            "[CANCEL] %s: cancelled %d/%d exit orders",
            position.get("stock_code"), cancelled, len(exit_ids),
        )


def determine_exit(position: dict, current_price: float) -> tuple[str, float] | None:
    """Returns (exit_reason, exit_price) or None if no exit needed."""

    # Check server-side order fills first (SL/trailing stop executed on moomoo)
    if SERVER_SIDE_EXITS_ENABLED:
        server_fill = check_server_side_fills(position)
        if server_fill is not None:
            return server_fill

    # Polling-based SL/TP check (always active as safety net)
    # Even with server-side exits, price might gap through the stop
    if check_stop_loss(position, current_price):
        return ("stop_loss", current_price)

    if not SERVER_SIDE_EXITS_ENABLED:
        if check_take_profit(position, current_price):
            return ("take_profit", float(position["take_profit"]))

    # Time expiry (always checked — server-side orders don't handle this)
    signal = position.get("us_signals") or {}
    strategy = signal.get("strategy", "strategy_a")
    _MAX_DAYS = {
        "strategy_a": MAX_HOLDING_DAYS_A,
        "strategy_b": MAX_HOLDING_DAYS_B,
        "strategy_c": MAX_HOLDING_DAYS_C,
        "strategy_d": MAX_HOLDING_DAYS_D,
    }
    max_days = _MAX_DAYS.get(strategy, MAX_HOLDING_DAYS_A)

    # Extend holding period if position is profitable (let trailing stop manage exit)
    entry_price = float(position.get("entry_price", 0))
    if entry_price > 0:
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        if profit_pct >= 30:
            max_days = int(max_days * 2)  # double holding for big winners
        elif profit_pct >= 15:
            max_days = int(max_days * 1.5)  # 50% extension for solid profits

    if check_time_expiry(position, max_days):
        return ("time_expiry", current_price)

    # Claude AI exit advisor (only when no hard exit triggered)
    if CLAUDE_EXIT_ENABLED:
        try:
            advice = advise_exit(position, current_price)
            if advice.should_exit and advice.suggested_action == "sell_now":
                log.info(
                    "[CLAUDE-EXIT] %s: sell_now — %s",
                    position.get("stock_code"),
                    advice.reasoning,
                )
                return ("claude_exit", current_price)
            if advice.suggested_action == "tighten_sl" and SERVER_SIDE_EXITS_ENABLED:
                _tighten_server_side_sl(position, current_price)
        except Exception as e:
            log.warning("Claude exit advisor error: %s", e)

    return None


def _tighten_server_side_sl(position: dict, current_price: float) -> None:
    """Replace the server-side SL order with a tighter one (midpoint entry<->current)."""
    entry_price = float(position.get("entry_price", 0))
    old_sl = float(position.get("stop_loss") or 0)
    new_sl = round((entry_price + current_price) / 2, 2)

    if new_sl <= old_sl or new_sl >= current_price:
        return  # Don't lower the SL or set it above current price

    stock_code = position.get("stock_code", "")
    qty = int(position.get("quantity", 0))
    order_ids = position.get("moomoo_order_ids") or []

    # Cancel old SL order (index 1 is typically the SL order)
    if len(order_ids) > 1:
        cancel_order(order_ids[1])

    # Place new tighter SL
    result = place_stop_sell(stock_code, qty, new_sl)
    if result.success:
        # Update position record with new SL and order ID
        new_order_ids = list(order_ids)
        if len(new_order_ids) > 1:
            new_order_ids[1] = result.order_id
        else:
            new_order_ids.append(result.order_id)

        sb.table("us_positions").update({
            "stop_loss": new_sl,
            "moomoo_order_ids": new_order_ids,
        }).eq("id", position["id"]).execute()

        log.info(
            "[TIGHTEN-SL] %s: SL $%.2f -> $%.2f (order: %s)",
            stock_code, old_sl, new_sl, result.order_id,
        )
    else:
        log.warning("[TIGHTEN-SL] %s: failed to place new SL: %s", stock_code, result.message)
