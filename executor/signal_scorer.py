"""Signal scoring and grading — port from TypeScript lib/signal-scorer.ts."""

from __future__ import annotations

from constants import (
    SCORE_A_GRADE_A_MIN, SCORE_A_GRADE_B_MIN, SCORE_A_GRADE_C_MIN,
    SCORE_B_GRADE_A_MIN, SCORE_B_GRADE_B_MIN, SCORE_B_GRADE_C_MIN,
    SCORE_C_GRADE_A_MIN, SCORE_C_GRADE_B_MIN, SCORE_C_GRADE_C_MIN,
    STRATEGY_B_LOW_VOL_THRESHOLD, STRATEGY_B_LOW_VOL_PENALTY,
    STRATEGY_C_BELOW_KUMO_PENALTY,
)


def _to_grade(score: int, a_min: int, b_min: int, c_min: int) -> str:
    if score >= a_min:
        return "A"
    if score >= b_min:
        return "B"
    if score >= c_min:
        return "C"
    return "D"


def score_strategy_a(result, ctx: dict) -> tuple[int, str]:
    """Score Strategy A (N-Day High Breakout) result. Returns (score, grade)."""
    if not result.triggered:
        return 0, "D"

    score = 45  # base

    # Breakout strength: moderate breakouts outperform extreme ones
    if result.breakout_pct is not None:
        if 0.5 <= result.breakout_pct <= 2.5:
            score += 15  # sweet spot — not too early, not overextended
        elif result.breakout_pct < 0.5:
            score += 5   # marginal breakout
        else:
            score += 8   # overextended — higher risk of reversal

    # Volume surge: moderate surge is optimal
    if result.volume_ratio is not None:
        if 1.3 <= result.volume_ratio <= 2.0:
            score += 15  # healthy confirmation volume
        elif result.volume_ratio > 2.0:
            score += 8   # extreme volume can signal exhaustion
        else:
            score += 5

    adx = ctx.get("adx")
    if adx is not None and adx >= 25:
        score += 10

    regime = ctx.get("market_regime", "neutral")
    if regime == "bull":
        score += 10
    elif regime == "bear":
        score -= 20

    if ctx.get("stoch_cross_up"):
        score += 5

    score = max(0, min(100, score))
    return score, _to_grade(score, SCORE_A_GRADE_A_MIN, SCORE_A_GRADE_B_MIN, SCORE_A_GRADE_C_MIN)


def score_strategy_b(result, ctx: dict) -> tuple[int, str]:
    """Score Strategy B (Deep Oversold Reversal) result. Returns (score, grade)."""
    if not result.triggered:
        return 0, "D"

    score = 40  # base

    # RSI depth bonus: deeper oversold = stronger signal
    if result.rsi is not None:
        if result.rsi <= 25:
            score += 25
        elif result.rsi <= 28:
            score += 20
        else:
            score += 15

    # Strong reversal candle is core — already required for trigger
    if result.strong_reversal:
        score += 5

    # Both confirmations present = highest quality
    if result.volume_spike and result.macd_improving:
        score += 15
    elif result.macd_improving:
        score += 10
    elif result.volume_spike:
        score += 8

    regime = ctx.get("market_regime", "neutral")
    if regime == "bull":
        score += 5
    elif regime == "bear":
        score -= 15

    if ctx.get("stoch_cross_up"):
        score += 8

    score = max(0, min(100, score))
    return score, _to_grade(score, SCORE_B_GRADE_A_MIN, SCORE_B_GRADE_B_MIN, SCORE_B_GRADE_C_MIN)


def score_strategy_c(result, ctx: dict) -> tuple[int, str]:
    """Score Strategy C result. Returns (score, grade)."""
    if not result.triggered:
        return 0, "D"

    score = 45  # base

    if result.gc_days_ago == 1:
        score += 15
    elif result.gc_days_ago == 2:
        score += 10
    elif result.gc_days_ago == 3:
        score += 7
    else:
        score += 4

    adx = ctx.get("adx")
    if adx is not None and adx >= 25:
        score += 10

    regime = ctx.get("market_regime", "neutral")
    if regime == "bull":
        score += 10
    elif regime == "bear":
        score -= 20

    if ctx.get("price_above_kumo"):
        score += 5
    if ctx.get("price_below_kumo"):
        score += STRATEGY_C_BELOW_KUMO_PENALTY

    if ctx.get("sar_bull"):
        score += 3

    score = max(0, min(100, score))
    return score, _to_grade(score, SCORE_C_GRADE_A_MIN, SCORE_C_GRADE_B_MIN, SCORE_C_GRADE_C_MIN)
