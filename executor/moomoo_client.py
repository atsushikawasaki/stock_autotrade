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
    ModifyOrderOp,
)

from config import OPEND_HOST, OPEND_PORT, MOOMOO_TRADE_PWD, MOOMOO_SYMBOL_PREFIX, TRADE_ENV

_TRD_ENV = TrdEnv.SIMULATE if TRADE_ENV == "SIMULATE" else TrdEnv.REAL


@dataclass(frozen=True)
class OrderResult:
    success: bool
    order_id: str | None
    message: str


def _get_trade_ctx() -> OpenSecTradeContext:
    return OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=OPEND_HOST,
        port=OPEND_PORT,
        security_firm=SecurityFirm.FUTUJP,
    )


def to_moomoo_code(symbol: str) -> str:
    """Convert ticker to moomoo format: AAPL -> US.AAPL"""
    if symbol.startswith(MOOMOO_SYMBOL_PREFIX):
        return symbol
    return f"{MOOMOO_SYMBOL_PREFIX}{symbol}"


def unlock_trade() -> bool:
    """Unlock trading (required before placing orders on real account)."""
    if not MOOMOO_TRADE_PWD:
        print("[WARN] MOOMOO_TRADE_PWD not set — cannot unlock")
        return False

    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.unlock_trade(password=MOOMOO_TRADE_PWD, is_unlock=True)
        if ret == RET_OK:
            print("[OK] Trade unlocked")
            return True
        print(f"[FAIL] Unlock failed: {data}")
        return False
    finally:
        ctx.close()


def get_account_balance() -> float | None:
    """Get available buying power in USD."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.accinfo_query(trd_env=_TRD_ENV, currency=Currency.USD)
        if ret == RET_OK:
            power = data.iloc[0].get("power", 0)
            return float(power)
        print(f"[FAIL] Account query failed: {data}")
        return None
    finally:
        ctx.close()


def place_limit_buy(symbol: str, price: float, qty: int) -> OrderResult:
    """Place a limit buy order for a US stock."""
    code = to_moomoo_code(symbol)
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.place_order(
            price=price,
            qty=qty,
            code=code,
            trd_side=TrdSide.BUY,
            order_type=OrderType.NORMAL,
            trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            order_id = str(data["order_id"].iloc[0])
            return OrderResult(success=True, order_id=order_id, message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))
    finally:
        ctx.close()


def place_limit_sell(symbol: str, price: float, qty: int) -> OrderResult:
    """Place a limit sell order for a US stock."""
    code = to_moomoo_code(symbol)
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.place_order(
            price=price,
            qty=qty,
            code=code,
            trd_side=TrdSide.SELL,
            order_type=OrderType.NORMAL,
            trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            order_id = str(data["order_id"].iloc[0])
            return OrderResult(success=True, order_id=order_id, message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))
    finally:
        ctx.close()


def place_market_sell(symbol: str, qty: int) -> OrderResult:
    """Place a market sell order (for urgent exits)."""
    code = to_moomoo_code(symbol)
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.place_order(
            price=0,
            qty=qty,
            code=code,
            trd_side=TrdSide.SELL,
            order_type=OrderType.MARKET,
            trd_env=_TRD_ENV,
        )
        if ret == RET_OK:
            order_id = str(data["order_id"].iloc[0])
            return OrderResult(success=True, order_id=order_id, message="OK")
        return OrderResult(success=False, order_id=None, message=str(data))
    finally:
        ctx.close()


def cancel_order(order_id: str) -> bool:
    """Cancel an existing order."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.modify_order(
            modify_order_op=ModifyOrderOp.CANCEL,
            order_id=order_id,
            qty=0,
            price=0,
            trd_env=_TRD_ENV,
        )
        return ret == RET_OK
    finally:
        ctx.close()


def get_open_orders() -> list[dict]:
    """Get list of currently open orders."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.order_list_query(trd_env=_TRD_ENV)
        if ret != RET_OK:
            return []
        active = data[
            ~data["order_status"].isin(["CANCELLED_ALL", "FILLED_ALL", "DELETED"])
        ]
        return active.to_dict("records")
    finally:
        ctx.close()


def get_positions() -> list[dict]:
    """Get current holdings."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.position_list_query(trd_env=_TRD_ENV)
        if ret != RET_OK:
            return []
        return data[data["qty"] > 0].to_dict("records") if len(data) > 0 else []
    finally:
        ctx.close()
