"""Position monitoring: checks exit conditions for open positions."""

from __future__ import annotations

from datetime import datetime, timezone

from moomoo import OpenQuoteContext, RET_OK

from config import OPEND_HOST, OPEND_PORT, MOOMOO_SYMBOL_PREFIX


def get_current_price(symbol: str) -> float | None:
    """Get current price for a US stock via moomoo quote API."""
    code = f"{MOOMOO_SYMBOL_PREFIX}{symbol}" if not symbol.startswith(MOOMOO_SYMBOL_PREFIX) else symbol
    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        # Subscribe first (required for US quotes)
        ret_sub, _ = ctx.subscribe([code], ["QUOTE"])
        if ret_sub != RET_OK:
            print(f"[WARN] Subscribe failed for {code}")
            return None

        ret, data = ctx.get_stock_quote([code])
        if ret == RET_OK and len(data) > 0:
            price = data.iloc[0].get("last_price", None)
            return float(price) if price is not None else None
        return None
    except Exception as e:
        print(f"[WARN] Quote failed for {symbol}: {e}")
        return None
    finally:
        ctx.close()


def check_stop_loss(position: dict, current_price: float) -> bool:
    """Check if current price hit stop loss."""
    sl = position.get("stop_loss")
    if sl is None:
        return False
    return current_price <= float(sl)


def check_take_profit(position: dict, current_price: float) -> bool:
    """Check if current price hit take profit."""
    tp = position.get("take_profit")
    if tp is None:
        return False
    return current_price >= float(tp)


def check_time_expiry(position: dict, max_days: int = 30) -> bool:
    """Check if position exceeded max holding days."""
    opened_at = position.get("opened_at")
    if not opened_at:
        return False
    opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - opened).days >= max_days


def determine_exit(position: dict, current_price: float) -> tuple[str, float] | None:
    """
    Determine if a position should be exited.
    Returns (exit_reason, exit_price) or None if no exit needed.
    """
    # Priority: SL > TP > Time expiry
    if check_stop_loss(position, current_price):
        return ("stop_loss", float(position["stop_loss"]))

    if check_take_profit(position, current_price):
        return ("take_profit", float(position["take_profit"]))

    # Strategy-specific max holding days
    signal = position.get("us_signals") or {}
    strategy = signal.get("strategy", "strategy_a")
    max_days = 10 if strategy == "strategy_b" else 30

    if check_time_expiry(position, max_days):
        return ("time_expiry", current_price)

    return None
