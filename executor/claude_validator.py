"""AI validation gate for entry signals and exit advice (Google Gemini)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import yfinance as yf
from google import genai

from config import GEMINI_API_KEY
from constants import (
    GEMINI_MODEL,
    CLAUDE_MIN_CONFIDENCE,
    GEMINI_TIMEOUT_SECONDS,
    CLAUDE_EARNINGS_BLACKOUT_DAYS,
)

log = logging.getLogger("ai_validator")

_client = None


def _get_client():
    """Lazy-init Gemini client. Returns None if no API key."""
    global _client
    if _client is not None:
        return _client
    if not GEMINI_API_KEY:
        return None
    _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    approved: bool
    confidence: int  # 0-100
    reasoning: str


@dataclass(frozen=True)
class ExitAdvice:
    should_exit: bool
    reasoning: str
    suggested_action: str  # "hold", "sell_now", "tighten_sl"


# ---------------------------------------------------------------------------
# Stock context via yfinance
# ---------------------------------------------------------------------------

_SECTOR_ETF_MAP = {
    "Technology": "XLK", "Healthcare": "XLV", "Financial Services": "XLF",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
    "Industrials": "XLI", "Energy": "XLE", "Utilities": "XLU",
    "Real Estate": "XLRE", "Basic Materials": "XLB",
    "Communication Services": "XLC",
}


def _fetch_sector_trend(symbol: str) -> dict:
    """Fetch the sector ETF's short-term trend for cross-validation."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        sector = info.get("sector", "")
        etf_symbol = _SECTOR_ETF_MAP.get(sector)
        if not etf_symbol:
            return {"sector": sector, "sector_etf": None, "sector_trend": "unknown"}

        etf = yf.Ticker(etf_symbol)
        hist = etf.history(period="10d")
        if hist is None or len(hist) < 5:
            return {"sector": sector, "sector_etf": etf_symbol, "sector_trend": "insufficient_data"}

        closes = hist["Close"].tolist()
        sma5 = sum(closes[-5:]) / 5
        trend = "bullish" if closes[-1] > sma5 else "bearish"
        change_5d = ((closes[-1] - closes[0]) / closes[0]) * 100
        return {
            "sector": sector,
            "sector_etf": etf_symbol,
            "sector_trend": trend,
            "sector_5d_change_pct": round(change_5d, 2),
        }
    except Exception:
        return {"sector": "", "sector_etf": None, "sector_trend": "unknown"}


def _fetch_stock_context(symbol: str) -> dict:
    """Fetch recent news headlines, next earnings date, and EPS estimates."""
    ctx: dict = {
        "news_headlines": [],
        "next_earnings_date": None,
        "earnings_estimate_eps": None,
        "last_earnings_surprise_pct": None,
        "days_to_earnings": None,
    }
    try:
        ticker = yf.Ticker(symbol)

        # News (top 3 headlines)
        news = ticker.get_news()
        if news:
            ctx["news_headlines"] = [
                item.get("title", "") for item in news[:3] if item.get("title")
            ]

        # Earnings calendar
        cal = ticker.calendar
        if cal is not None and isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
            if earnings_date:
                if isinstance(earnings_date, list) and len(earnings_date) > 0:
                    next_date = earnings_date[0]
                else:
                    next_date = earnings_date
                ctx["next_earnings_date"] = str(next_date)

                from datetime import datetime, timezone
                import pandas as pd
                if isinstance(next_date, (datetime, pd.Timestamp)):
                    now = datetime.now(timezone.utc)
                    if hasattr(next_date, "tzinfo") and next_date.tzinfo is None:
                        next_date = next_date.replace(tzinfo=timezone.utc)
                    delta = (next_date - now).days
                    ctx["days_to_earnings"] = max(delta, 0)

            eps_est = cal.get("Earnings Average") or cal.get("EPS Estimate")
            if eps_est is not None:
                ctx["earnings_estimate_eps"] = float(eps_est)

        # Last earnings surprise
        hist = ticker.earnings_history
        if hist is not None and not hist.empty:
            last_row = hist.iloc[-1]
            surprise = last_row.get("surprisePercent") or last_row.get("epsActual")
            if surprise is not None:
                ctx["last_earnings_surprise_pct"] = round(float(surprise), 2)

    except Exception as e:
        log.warning("Failed to fetch stock context for %s: %s", symbol, e)

    return ctx


# ---------------------------------------------------------------------------
# Entry validation
# ---------------------------------------------------------------------------

_ENTRY_SYSTEM_PROMPT = """\
You are a quantitative trading assistant that validates technical buy signals.
Your job is to review a signal and decide whether to APPROVE or REJECT it.

Analysis criteria:
1. Technical consistency: Do indicators align? (e.g., RSI contradicting MACD, \
false breakout on low volume)
2. Earnings proximity: If earnings are within {blackout} trading days, \
recommend caution or rejection.
3. News sentiment: Check headlines for clearly negative catalysts \
(lawsuit, downgrade, SEC investigation, guidance cut).
4. Risk/reward: Is the stop-loss too tight or take-profit unrealistic \
given the ATR and volatility?
5. Sector alignment: If the sector ETF trend is bearish while the stock signal \
is bullish, consider rejection or lower confidence. A stock fighting its sector \
headwind has lower odds.

Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{{"approved": true/false, "confidence": 0-100, "reasoning": "brief explanation"}}
""".replace("{blackout}", str(CLAUDE_EARNINGS_BLACKOUT_DAYS))


def _build_entry_prompt(signal: dict, context: dict) -> str:
    """Build user prompt with signal data and stock context."""
    data = {
        "stock_code": signal.get("stock_code"),
        "strategy": signal.get("strategy"),
        "grade": signal.get("grade"),
        "score": signal.get("score"),
        "entry_price": signal.get("entry_price"),
        "stop_loss": signal.get("stop_loss"),
        "take_profit": signal.get("take_profit"),
        "reason": signal.get("reason"),
        "indicators": signal.get("indicators"),
    }
    data.update(context)
    return json.dumps(data, default=str, ensure_ascii=False)


def validate_entry(signal: dict) -> ValidationResult:
    """
    Validate a buy signal using Gemini AI.

    Fail-closed: returns approved=False on API/parse errors to avoid risky entries.
    """
    client = _get_client()
    if client is None:
        log.info("[AI] No Gemini API key — skipping entry validation")
        return ValidationResult(approved=True, confidence=0, reasoning="no_api_key")

    symbol = signal.get("stock_code", "")
    context = _fetch_stock_context(symbol)
    sector_ctx = _fetch_sector_trend(symbol)
    context.update(sector_ctx)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=_ENTRY_SYSTEM_PROMPT + "\n\n" + _build_entry_prompt(signal, context),
            config={
                "max_output_tokens": 256,
                "response_mime_type": "application/json",
            },
        )

        text = response.text.strip()
        parsed = json.loads(text)

        approved = bool(parsed.get("approved", False))
        confidence = int(parsed.get("confidence", 0))
        reasoning = str(parsed.get("reasoning", ""))

        # Apply minimum confidence threshold
        if approved and confidence < CLAUDE_MIN_CONFIDENCE:
            approved = False
            reasoning = f"Low confidence ({confidence}): {reasoning}"

        log.info(
            "[AI] %s %s (confidence:%d): %s",
            symbol,
            "approved" if approved else "rejected",
            confidence,
            reasoning,
        )
        return ValidationResult(
            approved=approved,
            confidence=confidence,
            reasoning=reasoning,
        )

    except Exception as e:
        log.warning("[AI] Error for %s — fail-closed (rejected): %s", symbol, e)
        return ValidationResult(approved=False, confidence=0, reasoning=f"api_error: {e}")


# ---------------------------------------------------------------------------
# Exit advisor
# ---------------------------------------------------------------------------

_EXIT_SYSTEM_PROMPT = """\
You are a quantitative trading assistant advising on whether to exit a position.
You receive position data including entry price, current price, P&L, holding days, \
and market context.

Decision options:
- "hold": Maintain position. Momentum intact, no immediate risk.
- "sell_now": Exit immediately. Approaching earnings, negative news, \
weakening momentum, or risk/reward no longer favorable.
- "tighten_sl": Raise stop-loss closer to current price to lock in gains \
while allowing further upside.

Respond with ONLY a JSON object (no markdown):
{{"should_exit": true/false, "suggested_action": "hold"|"sell_now"|"tighten_sl", \
"reasoning": "brief explanation"}}
"""


def _build_exit_prompt(position: dict, current_price: float) -> str:
    """Build user prompt with position data and context."""
    entry_price = float(position.get("entry_price", 0))
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

    opened_at = position.get("opened_at", "")
    holding_days = 0
    if opened_at:
        from datetime import datetime, timezone
        try:
            opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
            holding_days = (datetime.now(timezone.utc) - opened).days
        except (ValueError, TypeError):
            pass

    signal = position.get("us_signals") or {}
    symbol = position.get("stock_code", "")
    context = _fetch_stock_context(symbol)

    data = {
        "stock_code": symbol,
        "entry_price": entry_price,
        "current_price": current_price,
        "unrealized_pnl_pct": round(pnl_pct, 2),
        "stop_loss": position.get("stop_loss"),
        "take_profit": position.get("take_profit"),
        "holding_days": holding_days,
        "strategy": signal.get("strategy", "unknown"),
        "indicators_at_entry": signal.get("indicators"),
    }
    data.update(context)
    return json.dumps(data, default=str, ensure_ascii=False)


def advise_exit(position: dict, current_price: float) -> ExitAdvice:
    """
    Get Gemini's advice on whether to exit a position.

    Fail-open: returns should_exit=False on any API error (defer to existing logic).
    """
    client = _get_client()
    if client is None:
        return ExitAdvice(should_exit=False, reasoning="no_api_key", suggested_action="hold")

    symbol = position.get("stock_code", "")

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=_EXIT_SYSTEM_PROMPT + "\n\n" + _build_exit_prompt(position, current_price),
            config={
                "max_output_tokens": 256,
                "response_mime_type": "application/json",
            },
        )

        text = response.text.strip()
        parsed = json.loads(text)

        should_exit = bool(parsed.get("should_exit", False))
        action = str(parsed.get("suggested_action", "hold"))
        reasoning = str(parsed.get("reasoning", ""))

        if action not in ("hold", "sell_now", "tighten_sl"):
            action = "hold"

        log.info("[AI-EXIT] %s: %s (%s)", symbol, action, reasoning)
        return ExitAdvice(
            should_exit=should_exit,
            reasoning=reasoning,
            suggested_action=action,
        )

    except Exception as e:
        log.warning("[AI-EXIT] Error for %s — fail-open: %s", symbol, e)
        return ExitAdvice(should_exit=False, reasoning=f"api_error: {e}", suggested_action="hold")
