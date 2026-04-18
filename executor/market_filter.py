"""Market regime detection and entry gate.

Determines whether the overall market environment is suitable for new entries.
Uses SPY SMA50/200, SMA spread, and VIX to classify:
  - bull: SMA50 > SMA200, VIX normal
  - neutral: mixed signals
  - bear: SMA50 < SMA200, confirmed downtrend
  - caution: elevated VIX or weakening trend (not full bear)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from indicators import calc_sma
from price_client import PriceRow, fetch_daily_prices
from constants import (
    MARKET_INDEX_SYMBOL,
    MARKET_SMA_FAST,
    MARKET_SMA_SLOW,
    MARKET_VIX_CAUTION,
    MARKET_VIX_BLOCK,
    MARKET_SMA_SPREAD_BEAR,
    MARKET_SPY_BELOW_SMA200_DAYS,
    MARKET_GATE_STRATEGY_A_BEAR,
    MARKET_GATE_STRATEGY_A_CAUTION,
    MARKET_GATE_STRATEGY_B_BEAR,
    MARKET_GATE_STRATEGY_C_BEAR,
    MARKET_GATE_STRATEGY_C_CAUTION,
    MARKET_GATE_STRATEGY_D_BEAR,
    MARKET_GATE_STRATEGY_D_CAUTION,
)

log = logging.getLogger("market_filter")

MarketRegime = str  # 'bull' | 'bear' | 'neutral' | 'caution'

_cache: dict[str, tuple[object, float]] = {}
_CACHE_TTL = 3600  # 1 hour


# ─── Data Types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MarketState:
    """Full market environment snapshot."""
    regime: MarketRegime
    vix: float | None
    sma_spread_pct: float | None     # (SMA50 - SMA200) / SMA200 * 100
    spy_below_sma200_days: int       # consecutive days SPY closed below SMA200
    entry_blocked: bool              # True = no new entries at all
    reason: str


@dataclass(frozen=True)
class EntryGate:
    """Per-signal entry decision."""
    allowed: bool
    reason: str


# ─── VIX ─────────────────────────────────────────────────────────────────────


def _fetch_vix() -> float | None:
    """Fetch current VIX value. Uses yfinance (VIX index not on moomoo)."""
    cached = _cache.get("vix")
    if cached and time.time() - cached[1] < _CACHE_TTL:
        return cached[0]  # type: ignore[return-value]

    try:
        import yfinance as yf
        t = yf.Ticker("^VIX")
        info = t.fast_info
        vix = getattr(info, "last_price", None)
        if vix is None:
            vix = getattr(info, "previous_close", None)
        if vix is not None:
            vix = float(vix)
            _cache["vix"] = (vix, time.time())
        return vix
    except Exception as e:
        log.warning("VIX fetch failed: %s", e)
        return None


# ─── Regime Detection ────────────────────────────────────────────────────────


def _count_days_below_sma200(closes: list[float], sma200: list[float | None]) -> int:
    """Count consecutive recent days where close < SMA200 (from latest)."""
    count = 0
    for i in range(len(closes) - 1, -1, -1):
        if sma200[i] is None:
            break
        if closes[i] < sma200[i]:
            count += 1
        else:
            break
    return count


def get_market_state() -> MarketState:
    """Full market environment analysis."""
    cached = _cache.get("state")
    if cached and time.time() - cached[1] < _CACHE_TTL:
        return cached[0]  # type: ignore[return-value]

    vix = _fetch_vix()

    try:
        # Request ~1.5x calendar days to ensure enough trading days for SMA200
        fetch_days = int(MARKET_SMA_SLOW * 1.5)
        prices = fetch_daily_prices(MARKET_INDEX_SYMBOL, fetch_days)
        if len(prices) < MARKET_SMA_SLOW + 1:
            state = MarketState(
                regime="neutral", vix=vix, sma_spread_pct=None,
                spy_below_sma200_days=0, entry_blocked=False,
                reason="Insufficient SPY data",
            )
            _cache["state"] = (state, time.time())
            return state

        closes = [p.close for p in prices]
        sma_fast = calc_sma(closes, MARKET_SMA_FAST)
        sma_slow = calc_sma(closes, MARKET_SMA_SLOW)

        last = len(closes) - 1
        f = sma_fast[last]
        s = sma_slow[last]

        if f is None or s is None:
            state = MarketState(
                regime="neutral", vix=vix, sma_spread_pct=None,
                spy_below_sma200_days=0, entry_blocked=False,
                reason="SMA not available",
            )
            _cache["state"] = (state, time.time())
            return state

        # SMA spread: how far SMA50 is above/below SMA200
        spread_pct = round(((f - s) / s) * 100, 2)

        # Days below SMA200
        days_below = _count_days_below_sma200(closes, sma_slow)

        # Determine regime
        regime: MarketRegime
        entry_blocked = False
        reasons: list[str] = []

        # Check VIX first (overrides SMA-based regime)
        if vix is not None and vix >= MARKET_VIX_BLOCK:
            regime = "bear"
            entry_blocked = True
            reasons.append(f"VIX {vix:.1f} >= {MARKET_VIX_BLOCK} (extreme fear)")
        elif spread_pct <= MARKET_SMA_SPREAD_BEAR and days_below >= MARKET_SPY_BELOW_SMA200_DAYS:
            regime = "bear"
            reasons.append(f"SMA spread {spread_pct:.1f}% (strong bear)")
            reasons.append(f"SPY below SMA200 for {days_below}d")
        elif f < s:
            # SMA50 < SMA200 but not extreme
            if days_below >= MARKET_SPY_BELOW_SMA200_DAYS:
                regime = "bear"
                reasons.append(f"SMA50 < SMA200, below for {days_below}d")
            else:
                regime = "caution"
                reasons.append(f"SMA50 < SMA200 (spread {spread_pct:.1f}%)")
        elif vix is not None and vix >= MARKET_VIX_CAUTION:
            regime = "caution"
            reasons.append(f"VIX {vix:.1f} >= {MARKET_VIX_CAUTION} (elevated)")
        else:
            regime = "bull"
            reasons.append(f"SMA50 > SMA200 (spread +{spread_pct:.1f}%)")
            if vix is not None:
                reasons.append(f"VIX {vix:.1f}")

        state = MarketState(
            regime=regime,
            vix=vix,
            sma_spread_pct=spread_pct,
            spy_below_sma200_days=days_below,
            entry_blocked=entry_blocked,
            reason=" | ".join(reasons),
        )
        _cache["state"] = (state, time.time())
        return state

    except Exception as e:
        log.warning("Market state detection failed: %s", e)
        return MarketState(
            regime="neutral", vix=vix, sma_spread_pct=None,
            spy_below_sma200_days=0, entry_blocked=False,
            reason=f"Error: {e}",
        )


def get_market_regime() -> MarketRegime:
    """Simple regime string (backward compatible)."""
    return get_market_state().regime


# ─── Entry Gate ──────────────────────────────────────────────────────────────


def _get_gate_rule(strategy: str, regime: MarketRegime) -> str:
    """Get entry gate rule for a strategy+regime combination."""
    if regime == "bull" or regime == "neutral":
        return "allow"

    gate_map = {
        ("strategy_a", "bear"): MARKET_GATE_STRATEGY_A_BEAR,
        ("strategy_a", "caution"): MARKET_GATE_STRATEGY_A_CAUTION,
        ("strategy_b", "bear"): MARKET_GATE_STRATEGY_B_BEAR,
        ("strategy_b", "caution"): "allow",  # reversal strategy OK in caution
        ("strategy_c", "bear"): MARKET_GATE_STRATEGY_C_BEAR,
        ("strategy_c", "caution"): MARKET_GATE_STRATEGY_C_CAUTION,
        ("strategy_d", "bear"): MARKET_GATE_STRATEGY_D_BEAR,
        ("strategy_d", "caution"): MARKET_GATE_STRATEGY_D_CAUTION,
    }
    return gate_map.get((strategy, regime), "allow")


def check_entry_gate(strategy: str, grade: str, market_state: MarketState | None = None) -> EntryGate:
    """
    Check if a signal should be allowed entry given current market conditions.

    Args:
        strategy: 'strategy_a', 'strategy_b', 'strategy_c'
        grade: 'A', 'B', 'C', 'D'
        market_state: pre-fetched state (or None to fetch fresh)

    Returns:
        EntryGate with allowed=True/False and reason.
    """
    state = market_state or get_market_state()

    # VIX extreme → block everything
    if state.entry_blocked:
        return EntryGate(allowed=False, reason=f"Market blocked: {state.reason}")

    rule = _get_gate_rule(strategy, state.regime)

    if rule == "block":
        return EntryGate(
            allowed=False,
            reason=f"{strategy} blocked in {state.regime} market ({state.reason})",
        )

    if rule == "grade_a_only" and grade != "A":
        return EntryGate(
            allowed=False,
            reason=f"{strategy} grade {grade} blocked in {state.regime} (A-grade only). {state.reason}",
        )

    return EntryGate(allowed=True, reason=f"{state.regime} market: {state.reason}")
