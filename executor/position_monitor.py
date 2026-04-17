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
    SERVER_SIDE_EXITS_ENABLED,
)
from claude_validator import advise_exit
from moomoo_client import query_order_fill, cancel_orders

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

    # Polling-based SL/TP check (fallback, or when server-side exits disabled)
    if not SERVER_SIDE_EXITS_ENABLED:
        if check_stop_loss(position, current_price):
            return ("stop_loss", float(position["stop_loss"]))

        if check_take_profit(position, current_price):
            return ("take_profit", float(position["take_profit"]))

    # Time expiry (always checked — server-side orders don't handle this)
    signal = position.get("us_signals") or {}
    strategy = signal.get("strategy", "strategy_a")
    _MAX_DAYS = {
        "strategy_a": MAX_HOLDING_DAYS_A,
        "strategy_b": MAX_HOLDING_DAYS_B,
        "strategy_c": MAX_HOLDING_DAYS_C,
    }
    max_days = _MAX_DAYS.get(strategy, MAX_HOLDING_DAYS_A)

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
        except Exception as e:
            log.warning("Claude exit advisor error: %s", e)

    return None
