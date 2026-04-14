"""Daily trade review: generates end-of-day analysis via Claude AI."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from anthropic import Anthropic, APIError, APITimeoutError
from supabase import create_client

from config import ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
from constants import CLAUDE_MODEL, CLAUDE_TIMEOUT_SECONDS
from market_filter import get_market_regime

log = logging.getLogger("daily_reviewer")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_REVIEW_SYSTEM_PROMPT = """\
You are a quantitative trading analyst reviewing today's trading activity.
Provide a concise daily review in markdown format (3-5 lines max).

Cover:
1. Performance summary (wins/losses, notable trades)
2. Strategy observations (which strategies worked, which didn't)
3. Risk flags (position concentration, upcoming earnings, market regime shift)
4. Action items for tomorrow

Be specific and data-driven. Use the provided data, not generic advice.
Respond in Japanese (the user's language).
"""


def _collect_daily_data(date_str: str) -> dict:
    """Collect all trading data for the given date."""
    # Signals created today
    signals = (
        sb.table("us_signals")
        .select("stock_code, strategy, grade, score, status, reason")
        .gte("signal_date", date_str)
        .lte("signal_date", date_str)
        .execute()
    ).data or []

    # Exits today
    exits = (
        sb.table("us_signal_outcomes")
        .select("signal_id, exit_price, exit_reason, return_pct, holding_days")
        .gte("exit_date", date_str)
        .lte("exit_date", date_str)
        .execute()
    ).data or []

    # Open positions
    open_positions = (
        sb.table("us_positions")
        .select("stock_code, entry_price, stop_loss, take_profit, opened_at")
        .in_("status", ["open", "partial_closed"])
        .execute()
    ).data or []

    # Cumulative stats (last 30 days of outcomes)
    recent_outcomes = (
        sb.table("us_signal_outcomes")
        .select("return_pct")
        .order("exit_date", desc=True)
        .limit(100)
        .execute()
    ).data or []

    total = len(recent_outcomes)
    wins = sum(1 for o in recent_outcomes if (o.get("return_pct") or 0) > 0)
    avg_return = (
        sum(o.get("return_pct", 0) for o in recent_outcomes) / total
        if total > 0
        else 0
    )

    return {
        "date": date_str,
        "market_regime": get_market_regime(),
        "signals_today": [
            {
                "stock": s.get("stock_code"),
                "strategy": s.get("strategy", "").replace("strategy_", "").upper(),
                "grade": s.get("grade"),
                "score": s.get("score"),
                "status": s.get("status"),
            }
            for s in signals
        ],
        "exits_today": [
            {
                "exit_reason": e.get("exit_reason"),
                "return_pct": e.get("return_pct"),
                "holding_days": e.get("holding_days"),
            }
            for e in exits
        ],
        "open_positions_count": len(open_positions),
        "cumulative_stats": {
            "total_trades": total,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "avg_return_pct": round(avg_return, 2),
        },
    }


def generate_daily_review() -> str | None:
    """
    Generate a daily trade review using Claude AI.

    Returns the review text (markdown), or None on failure.
    Saves the review to us_daily_reviews table.
    """
    if not ANTHROPIC_API_KEY:
        log.info("[REVIEW] No API key — skipping daily review")
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = _collect_daily_data(today)

    # Skip if no activity
    if not data["signals_today"] and not data["exits_today"]:
        log.info("[REVIEW] No activity today — skipping review")
        return None

    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            timeout=CLAUDE_TIMEOUT_SECONDS,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(data, default=str, ensure_ascii=False),
                }
            ],
            system=_REVIEW_SYSTEM_PROMPT,
        )

        review_text = response.content[0].text.strip()

        # Save to Supabase
        sb.table("us_daily_reviews").upsert(
            {
                "review_date": today,
                "review_text": review_text,
                "signals_count": len(data["signals_today"]),
                "exits_count": len(data["exits_today"]),
            },
            on_conflict="review_date",
        ).execute()

        log.info("[REVIEW] Daily review generated and saved")
        return review_text

    except (APIError, APITimeoutError) as e:
        log.warning("[REVIEW] API error: %s", e)
        return None
    except Exception as e:
        log.warning("[REVIEW] Failed to generate review: %s", e)
        return None
