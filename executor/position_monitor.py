"""Position monitoring: checks exit conditions for open positions."""

from __future__ import annotations

from datetime import datetime, timezone

from price_client import fetch_current_price


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

    return None
