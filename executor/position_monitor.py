"""Position monitoring: checks exit conditions for open positions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from price_client import fetch_current_price
from constants import CLAUDE_EXIT_ENABLED
from claude_validator import advise_exit

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


def determine_exit(position: dict, current_price: float) -> tuple[str, float] | None:
    """Returns (exit_reason, exit_price) or None if no exit needed."""
    if check_stop_loss(position, current_price):
        return ("stop_loss", float(position["stop_loss"]))

    if check_take_profit(position, current_price):
        return ("take_profit", float(position["take_profit"]))

    signal = position.get("us_signals") or {}
    strategy = signal.get("strategy", "strategy_a")
    max_days = 10 if strategy == "strategy_b" else 30

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
            if advice.suggested_action == "tighten_sl":
                _tighten_stop_loss(position, current_price)
        except Exception as e:
            log.warning("Claude exit advisor error: %s", e)

    return None


def _tighten_stop_loss(position: dict, current_price: float) -> None:
    """Raise stop-loss to lock in gains (midpoint between entry and current)."""
    entry_price = float(position.get("entry_price", 0))
    old_sl = float(position.get("stop_loss") or 0)
    new_sl = round((entry_price + current_price) / 2, 2)

    if new_sl <= old_sl:
        return  # Don't lower the stop-loss

    try:
        sb.table("us_positions").update({
            "stop_loss": new_sl,
        }).eq("id", position["id"]).execute()

        log.info(
            "[CLAUDE-EXIT] %s: tightened SL $%.2f -> $%.2f",
            position.get("stock_code"),
            old_sl,
            new_sl,
        )
    except Exception as e:
        log.warning("Failed to tighten SL for %s: %s", position.get("stock_code"), e)
