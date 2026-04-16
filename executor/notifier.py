"""LINE Messaging API integration for trade events."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone


LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _send(message: str) -> bool:
    """Send a message via LINE Messaging API (push). Returns True on success."""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        return False

    payload = json.dumps({
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message.strip()}],
    }).encode("utf-8")

    req = urllib.request.Request(
        LINE_PUSH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[WARN] LINE push failed: {e}")
        return False


def is_enabled() -> bool:
    """Check if LINE notifications are configured."""
    return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID)


def notify_signal(
    stock_code: str,
    strategy: str,
    grade: str,
    score: int,
    entry_price: float,
    stop_loss: float | None,
    take_profit: float | None,
    reason: str,
) -> bool:
    """Notify when a new signal is detected."""
    label = strategy.replace("strategy_", "Strategy ").upper()
    sl_str = f"${stop_loss:.2f}" if stop_loss else "-"
    tp_str = f"${take_profit:.2f}" if take_profit else "-"

    msg = (
        f"\n[Signal] {stock_code} {label}"
        f"\nGrade: {grade} (score: {score})"
        f"\nEntry: ${entry_price:.2f}"
        f"\nSL: {sl_str} / TP: {tp_str}"
        f"\n{reason}"
    )
    return _send(msg)


def notify_order_executed(
    stock_code: str,
    strategy: str,
    qty: int,
    price: float,
    order_id: str,
) -> bool:
    """Notify when a buy order is executed."""
    label = strategy.replace("strategy_", "").upper()
    msg = (
        f"\n[Buy] {stock_code} Strategy {label}"
        f"\n{qty} shares @ ${price:.2f}"
        f"\nOrder ID: {order_id}"
    )
    return _send(msg)


def notify_order_failed(
    stock_code: str,
    strategy: str,
    error: str,
) -> bool:
    """Notify when an order fails."""
    label = strategy.replace("strategy_", "").upper()
    msg = (
        f"\n[Order FAIL] {stock_code} Strategy {label}"
        f"\nError: {error}"
    )
    return _send(msg)


def notify_exit(
    stock_code: str,
    exit_reason: str,
    entry_price: float,
    exit_price: float,
    qty: int,
    pnl: float,
) -> bool:
    """Notify when a position is exited."""
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    pnl_sign = "+" if pnl >= 0 else ""
    reason_label = exit_reason.replace("_", " ").title()

    msg = (
        f"\n[Exit] {stock_code} — {reason_label}"
        f"\n{qty} shares: ${entry_price:.2f} -> ${exit_price:.2f}"
        f"\nP&L: {pnl_sign}${pnl:.2f} ({pnl_sign}{pnl_pct:.1f}%)"
    )
    return _send(msg)


def notify_error(context: str, error: str) -> bool:
    """Notify on critical errors."""
    msg = f"\n[ERROR] {context}\n{error}"
    return _send(msg)


def notify_daily_review(review_text: str) -> bool:
    """Send Claude AI daily trade review via LINE."""
    msg = f"\n[AI Daily Review]\n{review_text}"
    return _send(msg)


def notify_daily_summary(
    signals_found: int,
    orders_executed: int,
    exits: int,
    total_pnl: float,
) -> bool:
    """Send end-of-day summary."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pnl_sign = "+" if total_pnl >= 0 else ""
    msg = (
        f"\n[Daily Summary] {now}"
        f"\nSignals: {signals_found}"
        f"\nOrders: {orders_executed}"
        f"\nExits: {exits}"
        f"\nDay P&L: {pnl_sign}${total_pnl:.2f}"
    )
    return _send(msg)
