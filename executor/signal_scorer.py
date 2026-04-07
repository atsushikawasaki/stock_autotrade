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
    """Score Strategy A result. Returns (score, grade)."""
    if not result.triggered:
        return 0, "D"

    score = 50  # base

    if result.rsi_cross_days_ago == 1:
        score += 15
    elif result.rsi_cross_days_ago == 2:
        score += 10

    if result.volume_surge:
        score += 10

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
    """Score Strategy B result. Returns (score, grade)."""
    if not result.triggered:
        return 0, "D"

    score = 55  # base

    rsi = ctx.get("rsi")
    if rsi is not None:
        if rsi <= 25:
            score += 20
        elif rsi <= 30:
            score += 15
        elif rsi <= 35:
            score += 10
        elif rsi <= 38:
            score += 5

    if result.macd_improving:
        score += 10

    vol_ratio = ctx.get("volume_ratio")
    if vol_ratio is not None:
        if vol_ratio >= 1.5:
            score += 10
        elif vol_ratio < STRATEGY_B_LOW_VOL_THRESHOLD:
            score += STRATEGY_B_LOW_VOL_PENALTY

    regime = ctx.get("market_regime", "neutral")
    if regime == "bull":
        score += 5
    elif regime == "bear":
        score -= 10

    if ctx.get("stoch_cross_up"):
        score += 5

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
