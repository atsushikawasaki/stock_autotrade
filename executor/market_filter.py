"""Market regime detection using SPY SMA50/200 crossover."""

from __future__ import annotations

import time

from indicators import calc_sma
from price_client import fetch_daily_prices
from constants import MARKET_INDEX_SYMBOL, MARKET_SMA_FAST, MARKET_SMA_SLOW

MarketRegime = str  # 'bull' | 'bear' | 'neutral'

_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 3600  # 1 hour


def get_market_regime() -> MarketRegime:
    """Determine market regime from SPY SMA50 vs SMA200."""
    cached = _cache.get("regime")
    if cached and time.time() - cached[1] < _CACHE_TTL:
        return cached[0]

    try:
        prices = fetch_daily_prices(MARKET_INDEX_SYMBOL, MARKET_SMA_SLOW + 50)
        if len(prices) < MARKET_SMA_SLOW:
            return "neutral"

        closes = [p.close for p in prices]
        sma_fast = calc_sma(closes, MARKET_SMA_FAST)
        sma_slow = calc_sma(closes, MARKET_SMA_SLOW)

        last = len(closes) - 1
        f = sma_fast[last]
        s = sma_slow[last]

        if f is None or s is None:
            return "neutral"

        regime: MarketRegime = "bull" if f > s else "bear"
        _cache["regime"] = (regime, time.time())
        return regime
    except Exception as e:
        print(f"[WARN] Market regime detection failed: {e}")
        return "neutral"
