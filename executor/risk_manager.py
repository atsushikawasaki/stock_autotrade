"""Risk management: daily loss limits, sector concentration, and position limits."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, MAX_POSITIONS

# ─── Risk Parameters ─────────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "3"))
MAX_SECTOR_POSITIONS = int(os.environ.get("MAX_SECTOR_POSITIONS", "3"))
MAX_CORRELATED_POSITIONS = int(os.environ.get("MAX_CORRELATED_POSITIONS", "5"))


@dataclass(frozen=True)
class RiskCheck:
    allowed: bool
    reason: str


sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def check_daily_loss(account_balance: float) -> RiskCheck:
    """Check if today's realized losses + unrealized open drawdown exceed the daily limit."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Realized losses today
    result = (
        sb.table("us_signal_outcomes")
        .select("return_pct")
        .eq("exit_date", today)
        .execute()
    )
    outcomes = result.data or []
    realized_loss_pct = sum(
        o["return_pct"] for o in outcomes if o["return_pct"] < 0
    )

    # 2. Unrealized losses from open positions
    unrealized_loss_pct = _calc_unrealized_loss_pct()

    total_loss_pct = realized_loss_pct + unrealized_loss_pct

    if abs(total_loss_pct) >= MAX_DAILY_LOSS_PCT:
        return RiskCheck(
            allowed=False,
            reason=(
                f"Daily loss limit hit: {total_loss_pct:.1f}% "
                f"(realized: {realized_loss_pct:.1f}%, unrealized: {unrealized_loss_pct:.1f}%, "
                f"max: -{MAX_DAILY_LOSS_PCT}%)"
            ),
        )

    return RiskCheck(
        allowed=True,
        reason=f"Daily loss: {total_loss_pct:.1f}% (limit: -{MAX_DAILY_LOSS_PCT}%)",
    )


def _calc_unrealized_loss_pct() -> float:
    """Sum of negative unrealized P&L % across all open positions."""
    from price_client import fetch_current_price

    positions = (
        sb.table("us_positions")
        .select("stock_code, entry_price, quantity")
        .in_("status", ["open", "partial_closed"])
        .execute()
    )
    open_positions = positions.data or []
    if not open_positions:
        return 0.0

    total_loss = 0.0
    for pos in open_positions:
        entry = float(pos.get("entry_price", 0))
        if entry <= 0:
            continue
        current = fetch_current_price(pos["stock_code"])
        if current is None:
            continue
        pnl_pct = ((current - entry) / entry) * 100
        if pnl_pct < 0:
            total_loss += pnl_pct

    return total_loss


def check_sector_concentration(stock_code: str) -> RiskCheck:
    """Check if adding this stock would over-concentrate a sector."""

    # Get sector for the target stock
    stock_result = sb.table("us_stocks").select("sector").eq("code", stock_code).execute()
    stock_data = stock_result.data or []
    if not stock_data or not stock_data[0].get("sector"):
        return RiskCheck(allowed=True, reason="No sector data — allowing")

    sector = stock_data[0]["sector"]

    # Count open positions in the same sector
    positions = (
        sb.table("us_positions")
        .select("stock_code")
        .in_("status", ["open", "partial_closed"])
        .execute()
    )
    open_codes = [p["stock_code"] for p in (positions.data or [])]

    if not open_codes:
        return RiskCheck(allowed=True, reason=f"No open positions in {sector}")

    # Count how many open positions share the same sector
    sector_result = (
        sb.table("us_stocks")
        .select("code, sector")
        .in_("code", open_codes)
        .eq("sector", sector)
        .execute()
    )
    same_sector_count = len(sector_result.data or [])

    if same_sector_count >= MAX_SECTOR_POSITIONS:
        return RiskCheck(
            allowed=False,
            reason=f"Sector limit: {same_sector_count} positions in {sector} (max: {MAX_SECTOR_POSITIONS})",
        )

    return RiskCheck(
        allowed=True,
        reason=f"{same_sector_count}/{MAX_SECTOR_POSITIONS} positions in {sector}",
    )


def check_position_limit() -> RiskCheck:
    """Check if we've reached the maximum number of concurrent positions."""
    result = (
        sb.table("us_positions")
        .select("id", count="exact")
        .in_("status", ["open", "partial_closed"])
        .execute()
    )
    count = result.count or 0

    if count >= MAX_POSITIONS:
        return RiskCheck(
            allowed=False,
            reason=f"Position limit reached: {count}/{MAX_POSITIONS}",
        )

    return RiskCheck(allowed=True, reason=f"{count}/{MAX_POSITIONS} positions open")


def check_all(stock_code: str, account_balance: float) -> RiskCheck:
    """Run all risk checks. Returns first failure or overall pass."""
    checks = [
        ("daily_loss", lambda: check_daily_loss(account_balance)),
        ("sector", lambda: check_sector_concentration(stock_code)),
        ("position_limit", lambda: check_position_limit()),
    ]

    reasons: list[str] = []
    for name, check_fn in checks:
        result = check_fn()
        if not result.allowed:
            return result
        reasons.append(result.reason)

    return RiskCheck(allowed=True, reason=" | ".join(reasons))
