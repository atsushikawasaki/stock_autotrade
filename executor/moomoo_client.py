"""moomoo OpenAPI client wrapper for US stock trading."""

from __future__ import annotations

import time
from dataclasses import dataclass

from moomoo import (
    OpenSecTradeContext,
    OrderType,
    RET_OK,
    SecurityFirm,
    Currency,
    TrdEnv,
    TrdMarket,
    TrdSide,
    TrailType,
    ModifyOrderOp,
)

from config import OPEND_HOST, OPEND_PORT, MOOMOO_TRADE_PWD, MOOMOO_SYMBOL_PREFIX, TRADE_ENV

import logging
import threading

_TRD_ENV = TrdEnv.SIMULATE if TRADE_ENV == "SIMULATE" else TrdEnv.REAL

log = logging.getLogger("moomoo_client")


@dataclass(frozen=True)
class OrderResult:
    success: bool
    order_id: str | None
    message: str


@dataclass(frozen=True)
class OrderFill:
    """Result of waiting for an order to fill."""
    filled: bool
    status: str           # FILLED_ALL, CANCELLED_ALL, TIMEOUT, ERROR, etc.
    dealt_qty: int        # actual filled quantity
    dealt_avg_price: float  # average fill price (0 if not filled)
    message: str


_ctx_lock = threading.Lock()
_shared_ctx: OpenSecTradeContext | None = None


def _get_trade_ctx() -> OpenSecTradeContext:
    """Get or create a shared trade context (thread-safe)."""
    global _shared_ctx
    with _ctx_lock:
        if _shared_ctx is None:
            _shared_ctx = OpenSecTradeContext(
                filter_trdmarket=TrdMarket.US,
                host=OPEND_HOST,
                port=OPEND_PORT,
                security_firm=SecurityFirm.FUTUJP,
            )
        return _shared_ctx


def _reset_ctx() -> None:
    """Close and reset the shared context (on connection errors)."""
    global _shared_ctx
    with _ctx_lock:
        if _shared_ctx is not None:
            try:
                _shared_ctx.close()
            except Exception:
                pass
            _shared_ctx = None


def to_moomoo_code(symbol: str) -> str:
    """Convert ticker to moomoo format: AAPL -> US.AAPL"""
    if symbol.startswith(MOOMOO_SYMBOL_PREFIX):
        return symbol
    return f"{MOOMOO_SYMBOL_PREFIX}{symbol}"


def _call_ctx(fn, *args, **kwargs):
    """Call a function on the shared context, retry once on connection error."""
    try:
        ctx = _get_trade_ctx()
        return fn(ctx, *args, **kwargs)
    except (ConnectionError, OSError, Exception) as e:
        if "connect" in str(e).lower() or "closed" in str(e).lower():
            log.warning("moomoo connection error, reconnecting: %s", e)
            _reset_ctx()
            ctx = _get_trade_ctx()
            return fn(ctx, *args, **kwargs)
        raise


def unlock_trade() -> bool:
    """Unlock trading (required before placing orders on real account)."""
    if not MOOMOO_TRADE_PWD:
        print("[WARN] MOOMOO_TRADE_PWD not set — cannot unlock")
        return False

    def _do(ctx):
        ret, data = ctx.unlock_trade(password=MOOMOO_TRADE_PWD, is_unlock=True)
        if ret == RET_OK:
            print("[OK] Trade unlocked")
            return True
        print(f"[FAIL] Unlock failed: {data}")
        return False

    return _call_ctx(_do)


def get_account_balance() -> float | None:
    """Get available buying power in USD."""
    def _do(ctx):
        ret, data = ctx.accinfo_query(trd_env=_TRD_ENV, currency=Currency.USD)
        if ret == RET_OK:
            power = data.iloc[0].get("power", 0)
            return float(power)
        print(f"[FAIL] Account query failed: {data}")
        return None

    return _call_ctx(_do)


def place_limit_buy(symbol: str, price: float, qty: int) -> OrderResult:
    """Place a limit buy order for a US stock."""
    code = to_moomoo_code(symbol)

    def _do(ctx):
        ret, data = ctx.place_order(
            price=price, qty=qty, code=code,
            trd_side=TrdSide.BUY, order_type=OrderType.NORMAL, trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            return OrderResult(success=True, order_id=str(data["order_id"].iloc[0]), message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))

    return _call_ctx(_do)


def place_limit_sell(symbol: str, price: float, qty: int) -> OrderResult:
    """Place a limit sell order for a US stock."""
    code = to_moomoo_code(symbol)

    def _do(ctx):
        ret, data = ctx.place_order(
            price=price, qty=qty, code=code,
            trd_side=TrdSide.SELL, order_type=OrderType.NORMAL, trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            return OrderResult(success=True, order_id=str(data["order_id"].iloc[0]), message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))

    return _call_ctx(_do)


def place_market_sell(symbol: str, qty: int) -> OrderResult:
    """Place a market sell order (for urgent exits)."""
    code = to_moomoo_code(symbol)

    def _do(ctx):
        ret, data = ctx.place_order(
            price=0, qty=qty, code=code,
            trd_side=TrdSide.SELL, order_type=OrderType.MARKET, trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            return OrderResult(success=True, order_id=str(data["order_id"].iloc[0]), message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))

    return _call_ctx(_do)


def cancel_order(order_id: str) -> bool:
    """Cancel an existing order."""
    def _do(ctx):
        ret, data = ctx.modify_order(
            modify_order_op=ModifyOrderOp.CANCEL,
            order_id=order_id, qty=0, price=0, trd_env=_TRD_ENV,
        )
        return ret == RET_OK

    return _call_ctx(_do)


def get_open_orders() -> list[dict]:
    """Get list of currently open orders."""
    def _do(ctx):
        ret, data = ctx.order_list_query(trd_env=_TRD_ENV)
        if ret != RET_OK:
            return []
        active = data[
            ~data["order_status"].isin(["CANCELLED_ALL", "FILLED_ALL", "DELETED"])
        ]
        return active.to_dict("records")

    return _call_ctx(_do)


def get_positions() -> list[dict]:
    """Get current holdings."""
    def _do(ctx):
        ret, data = ctx.position_list_query(trd_env=_TRD_ENV)
        if ret != RET_OK:
            return []
        return data[data["qty"] > 0].to_dict("records") if len(data) > 0 else []

    return _call_ctx(_do)


def place_stop_sell(symbol: str, qty: int, stop_price: float) -> OrderResult:
    """Place a stop-loss sell order (GTC). Triggers market sell when price <= stop_price."""
    code = to_moomoo_code(symbol)

    def _do(ctx):
        ret, data = ctx.place_order(
            price=0, qty=qty, code=code,
            trd_side=TrdSide.SELL,
            order_type=OrderType.STOP,
            aux_price=stop_price,
            time_in_force="GTC",
            trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            return OrderResult(success=True, order_id=str(data["order_id"].iloc[0]), message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))

    return _call_ctx(_do)


def place_trailing_stop_sell(
    symbol: str, qty: int, trail_ratio: float, trail_spread: float = 0,
) -> OrderResult:
    """Place a trailing stop sell order (GTC).

    Args:
        symbol: stock ticker
        qty: number of shares
        trail_ratio: trailing percentage (e.g. 5.0 for 5%)
        trail_spread: additional spread in dollars (default 0)
    """
    code = to_moomoo_code(symbol)

    def _do(ctx):
        ret, data = ctx.place_order(
            price=0, qty=qty, code=code,
            trd_side=TrdSide.SELL,
            order_type=OrderType.TRAILING_STOP,
            trail_type=TrailType.RATIO,
            trail_value=trail_ratio,
            trail_spread=trail_spread,
            time_in_force="GTC",
            trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            return OrderResult(success=True, order_id=str(data["order_id"].iloc[0]), message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))

    return _call_ctx(_do)


def place_take_profit_sell(symbol: str, qty: int, trigger_price: float) -> OrderResult:
    """Place a take-profit sell (MARKET_IF_TOUCHED, GTC). Triggers when price >= trigger_price."""
    code = to_moomoo_code(symbol)

    def _do(ctx):
        ret, data = ctx.place_order(
            price=0, qty=qty, code=code,
            trd_side=TrdSide.SELL,
            order_type=OrderType.MARKET_IF_TOUCHED,
            aux_price=trigger_price,
            time_in_force="GTC",
            trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            return OrderResult(success=True, order_id=str(data["order_id"].iloc[0]), message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))

    return _call_ctx(_do)


def cancel_orders(order_ids: list[str]) -> int:
    """Cancel multiple orders. Returns count of successfully cancelled."""
    cancelled = 0
    for oid in order_ids:
        if cancel_order(oid):
            cancelled += 1
    return cancelled


def query_order_fill(order_id: str) -> OrderFill:
    """Query current fill status of an order."""
    def _do(ctx):
        ret, data = ctx.order_list_query(trd_env=_TRD_ENV)
        if ret != RET_OK:
            return OrderFill(
                filled=False, status="ERROR", dealt_qty=0,
                dealt_avg_price=0, message=f"order_list_query failed: {data}",
            )
        matched = data[data["order_id"].astype(str) == str(order_id)]
        if matched.empty:
            return OrderFill(
                filled=False, status="NOT_FOUND", dealt_qty=0,
                dealt_avg_price=0, message=f"Order {order_id} not found",
            )
        row = matched.iloc[0]
        status = str(row.get("order_status", ""))
        dealt_qty = int(row.get("dealt_qty", 0))
        dealt_avg_price = float(row.get("dealt_avg_price", 0))
        filled = status == "FILLED_ALL"
        return OrderFill(
            filled=filled, status=status, dealt_qty=dealt_qty,
            dealt_avg_price=dealt_avg_price, message=status,
        )

    return _call_ctx(_do)


def wait_for_fill(order_id: str, timeout_seconds: int = 30, poll_interval: int = 3) -> OrderFill:
    """Poll order status until filled, cancelled, or timeout.

    Returns OrderFill with the final state. If still pending at timeout,
    cancels the order and returns TIMEOUT status.
    """
    terminal_statuses = {"FILLED_ALL", "FILLED_PART", "CANCELLED_ALL", "DELETED", "FAILED"}
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        fill = query_order_fill(order_id)
        if fill.status in terminal_statuses:
            return fill
        time.sleep(poll_interval)

    # Timeout — cancel the unfilled order
    log.warning("Order %s timed out after %ds, cancelling", order_id, timeout_seconds)
    cancel_order(order_id)

    # Final check after cancel
    fill = query_order_fill(order_id)
    if fill.filled:
        return fill
    return OrderFill(
        filled=False, status="TIMEOUT",
        dealt_qty=fill.dealt_qty, dealt_avg_price=fill.dealt_avg_price,
        message=f"Order not filled within {timeout_seconds}s (last: {fill.status})",
    )
