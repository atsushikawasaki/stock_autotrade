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


def _get_sb():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def check_daily_loss(account_balance: float) -> RiskCheck:
    """Check if today's realized losses exceed the daily limit."""
    sb = _get_sb()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    result = (
        sb.table("us_signal_outcomes")
        .select("return_pct")
        .eq("exit_date", today)
        .execute()
    )
    outcomes = result.data or []

    if not outcomes:
        return RiskCheck(allowed=True, reason="No exits today")

    total_loss_pct = sum(
        o["return_pct"] for o in outcomes if o["return_pct"] < 0
    )

    if abs(total_loss_pct) >= MAX_DAILY_LOSS_PCT:
        return RiskCheck(
            allowed=False,
            reason=f"Daily loss limit hit: {total_loss_pct:.1f}% (max: -{MAX_DAILY_LOSS_PCT}%)",
        )

    return RiskCheck(
        allowed=True,
        reason=f"Daily loss: {total_loss_pct:.1f}% (limit: -{MAX_DAILY_LOSS_PCT}%)",
    )


def check_sector_concentration(stock_code: str) -> RiskCheck:
    """Check if adding this stock would over-concentrate a sector."""
    sb = _get_sb()

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
    sb = _get_sb()
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
