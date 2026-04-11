"""Strategy A/B/C evaluation — port from TypeScript."""

from __future__ import annotations

from dataclasses import dataclass, field

from indicators import (
    calc_sma,
    calc_macd,
    calc_rsi,
    calc_atr,
    calc_adx,
    calc_bollinger_bands,
    calc_stochastic,
    calc_parabolic_sar,
    calc_ichimoku_kumo,
)
from price_client import PriceRow
from constants import (
    STRATEGY_A_ENABLED,
    STRATEGY_B_ENABLED,
    STRATEGY_C_ENABLED,
    STRATEGY_A_ADX_MIN,
    STRATEGY_A_BREAKOUT_LOOKBACK,
    STRATEGY_A_RSI_MIN,
    STRATEGY_A_RSI_MAX,
    STRATEGY_A_VOLUME_RATIO_MIN,
    STRATEGY_B_RSI_THRESHOLD,
    STRATEGY_B_BB_PROXIMITY_PCT,
    STRATEGY_B_VOLUME_RATIO_MIN,
    STRATEGY_B_CANDLE_BODY_PCT,
    STRATEGY_B_SMA_PERIOD,
    STRATEGY_C_ADX_MIN,
    STRATEGY_C_GC_LOOKBACK,
    STRATEGY_C_RSI_MIN,
    STRATEGY_C_RSI_MAX,
    STRATEGY_C_SL_ATR_MULT,
    STRATEGY_C_TP_ATR_MULT,
    SL_ATR_MULTIPLIER,
    TP_ATR_MULTIPLIER,
    SL_ATR_MULTIPLIER_BEAR,
    TP_ATR_MULTIPLIER_BULL,
)
from signal_scorer import score_strategy_a, score_strategy_b, score_strategy_c


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyAResult:
    """N-Day High Breakout: buy momentum breakouts with volume confirmation."""
    triggered: bool
    new_high: bool = False          # close > N-day high
    above_sma50: bool = False       # medium-term uptrend
    volume_surge: bool = False      # volume > 1.3x average
    macd_positive: bool = False
    rsi_in_range: bool = False
    rsi: float | None = None
    volume_ratio: float | None = None
    macd_histogram: float | None = None
    breakout_pct: float | None = None  # % above previous high


@dataclass(frozen=True)
class StrategyBResult:
    """Deep Oversold Reversal: only in long-term uptrend."""
    triggered: bool
    deep_oversold: bool = False     # RSI ≤ 30
    at_lower_bb: bool = False
    strong_reversal: bool = False   # bullish candle with strong body
    volume_spike: bool = False      # volume > 1.2x average
    above_sma200: bool = False      # long-term uptrend intact
    macd_improving: bool = False
    rsi: float | None = None
    bb_distance_pct: float | None = None
    volume_ratio: float | None = None
    macd_histogram: float | None = None


@dataclass(frozen=True)
class StrategyCResult:
    triggered: bool
    gc_confirmed: bool = False
    gc_days_ago: int | None = None
    macd_positive: bool = False
    rsi_in_range: bool = False
    rsi: float | None = None
    macd_histogram: float | None = None


@dataclass(frozen=True)
class EvaluatedSignal:
    strategy: str
    triggered: bool
    score: int
    grade: str
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    indicators: dict
    reason: str


# ─── Strategy Evaluators ──────────────────────────────────────────────────────

def evaluate_strategy_a(prices: list[PriceRow]) -> StrategyAResult:
    """N-Day High Breakout: buy when price breaks above N-day high with volume."""
    n = len(prices)
    if n < 80:
        return StrategyAResult(triggered=False)

    closes = [p.close for p in prices]
    highs = [p.high for p in prices]
    volumes = [p.volume for p in prices]

    sma50 = calc_sma(closes, 50)
    macd_line, signal_line = calc_macd(closes)
    rsi_line = calc_rsi(closes, 14)
    vol_sma20 = calc_sma([float(v) for v in volumes], 20)

    last = n - 1
    lookback = STRATEGY_A_BREAKOUT_LOOKBACK

    # 1. New N-day high: today's close > highest high of previous N days
    if last < lookback:
        return StrategyAResult(triggered=False)
    prev_high = max(highs[last - lookback : last])  # exclude today
    new_high = closes[last] > prev_high
    breakout_pct = ((closes[last] - prev_high) / prev_high) * 100 if prev_high > 0 else None

    # 2. Above SMA50 (medium-term uptrend)
    above_sma50 = sma50[last] is not None and closes[last] > sma50[last]

    # 3. Volume surge on breakout day
    vol_ratio = (
        (volumes[last] / vol_sma20[last]) if vol_sma20[last] and vol_sma20[last] > 0 else None
    )
    volume_surge = vol_ratio is not None and vol_ratio >= STRATEGY_A_VOLUME_RATIO_MIN

    # 4. MACD histogram positive (momentum confirmation)
    macd_val = macd_line[last]
    sig_val = signal_line[last]
    hist = (macd_val - sig_val) if (macd_val is not None and sig_val is not None) else None
    macd_positive = hist is not None and hist > 0

    # 5. RSI in momentum range (not overbought)
    rsi = rsi_line[last]
    rsi_in_range = rsi is not None and STRATEGY_A_RSI_MIN <= rsi <= STRATEGY_A_RSI_MAX

    triggered = new_high and above_sma50 and volume_surge and macd_positive and rsi_in_range

    return StrategyAResult(
        triggered=triggered,
        new_high=new_high,
        above_sma50=above_sma50,
        volume_surge=volume_surge,
        macd_positive=macd_positive,
        rsi_in_range=rsi_in_range,
        rsi=rsi,
        volume_ratio=vol_ratio,
        macd_histogram=hist,
        breakout_pct=breakout_pct,
    )


def evaluate_strategy_b(prices: list[PriceRow]) -> StrategyBResult:
    """Deep Oversold Reversal: only buy reversals in stocks with long-term uptrend."""
    n = len(prices)
    if n < STRATEGY_B_SMA_PERIOD + 10:
        return StrategyBResult(triggered=False)

    closes = [p.close for p in prices]
    volumes = [p.volume for p in prices]

    sma_long = calc_sma(closes, STRATEGY_B_SMA_PERIOD)
    upper, middle, lower = calc_bollinger_bands(closes, 20, 2)
    macd_line, signal_line = calc_macd(closes)
    rsi_line = calc_rsi(closes, 14)
    vol_sma20 = calc_sma([float(v) for v in volumes], 20)

    last = n - 1
    curr_close = closes[last]
    curr_open = prices[last].open
    curr_high = prices[last].high
    curr_low = prices[last].low
    curr_lower = lower[last]

    # 1. Deep oversold: RSI ≤ 30
    rsi = rsi_line[last]
    deep_oversold = rsi is not None and rsi <= STRATEGY_B_RSI_THRESHOLD

    # 2. At or below lower BB
    bb_dist_pct: float | None = None
    if curr_lower is not None and curr_lower > 0:
        bb_dist_pct = ((curr_close - curr_lower) / curr_lower) * 100
    at_lower_bb = bb_dist_pct is not None and bb_dist_pct <= STRATEGY_B_BB_PROXIMITY_PCT

    # 3. Strong bullish reversal candle: close > open, body >= 40% of range
    candle_range = curr_high - curr_low
    candle_body = curr_close - curr_open
    strong_reversal = (
        candle_body > 0
        and candle_range > 0
        and (candle_body / candle_range) * 100 >= STRATEGY_B_CANDLE_BODY_PCT
    )

    # 4. Volume spike (capitulation/reversal volume)
    vol_ratio = (
        (volumes[last] / vol_sma20[last]) if vol_sma20[last] and vol_sma20[last] > 0 else None
    )
    volume_spike = vol_ratio is not None and vol_ratio >= STRATEGY_B_VOLUME_RATIO_MIN

    # 5. Price above SMA (long-term uptrend — avoid falling knives)
    above_sma200 = sma_long[last] is not None and curr_close > sma_long[last]

    # 6. MACD histogram improving
    macd_last = macd_line[last]
    sig_last = signal_line[last]
    macd_prev = macd_line[last - 1]
    sig_prev = signal_line[last - 1]
    hist_last = (macd_last - sig_last) if (macd_last is not None and sig_last is not None) else None
    hist_prev = (macd_prev - sig_prev) if (macd_prev is not None and sig_prev is not None) else None
    macd_improving = hist_last is not None and hist_prev is not None and hist_last > hist_prev

    # Trigger: all core conditions + at least one confirmation
    triggered = (
        deep_oversold
        and at_lower_bb
        and strong_reversal
        and above_sma200
        and (volume_spike or macd_improving)  # at least one confirmation
    )

    return StrategyBResult(
        triggered=triggered,
        deep_oversold=deep_oversold,
        at_lower_bb=at_lower_bb,
        strong_reversal=strong_reversal,
        volume_spike=volume_spike,
        above_sma200=above_sma200,
        macd_improving=macd_improving,
        rsi=rsi,
        bb_distance_pct=bb_dist_pct,
        volume_ratio=vol_ratio,
        macd_histogram=hist_last,
    )


def evaluate_strategy_c(prices: list[PriceRow]) -> StrategyCResult:
    n = len(prices)
    if n < 80:
        return StrategyCResult(triggered=False)

    closes = [p.close for p in prices]
    sma25 = calc_sma(closes, 25)
    sma75 = calc_sma(closes, 75)
    macd_line, signal_line = calc_macd(closes)
    rsi_line = calc_rsi(closes, 14)

    last = n - 1

    gc_confirmed = False
    gc_days_ago: int | None = None
    for days_ago in range(1, STRATEGY_C_GC_LOOKBACK + 1):
        i = last - days_ago + 1
        prev = i - 1
        if prev < 0:
            break
        s25c, s25p = sma25[i], sma25[prev]
        s75c, s75p = sma75[i], sma75[prev]
        if all(v is not None for v in (s25c, s75c, s25p, s75p)):
            if s25p <= s75p and s25c > s75c:  # type: ignore[operator]
                gc_confirmed = True
                gc_days_ago = days_ago
                break

    macd_val = macd_line[last]
    sig_val = signal_line[last]
    hist = (macd_val - sig_val) if (macd_val is not None and sig_val is not None) else None
    macd_positive = hist is not None and hist > 0

    rsi = rsi_line[last]
    rsi_in_range = rsi is not None and STRATEGY_C_RSI_MIN <= rsi <= STRATEGY_C_RSI_MAX

    triggered = gc_confirmed and macd_positive and rsi_in_range

    return StrategyCResult(
        triggered=triggered,
        gc_confirmed=gc_confirmed,
        gc_days_ago=gc_days_ago,
        macd_positive=macd_positive,
        rsi_in_range=rsi_in_range,
        rsi=rsi,
        macd_histogram=hist,
    )


# ─── Risk Levels ──────────────────────────────────────────────────────────────

def calc_risk_levels(
    entry: float,
    atr: float | None,
    tp_override: float | None = None,
    sl_mult: float = SL_ATR_MULTIPLIER,
    tp_mult: float = TP_ATR_MULTIPLIER,
) -> tuple[float | None, float | None]:
    """Returns (stop_loss, take_profit)."""
    if atr is None or atr <= 0:
        return None, None
    sl = round(entry - sl_mult * atr, 2)
    tp = round(tp_override, 2) if tp_override is not None else round(entry + tp_mult * atr, 2)
    return sl, tp


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def evaluate_all_strategies(
    prices: list[PriceRow], market_regime: str
) -> list[EvaluatedSignal]:
    """Run all strategies on a stock's price history. Returns triggered signals sorted by score."""
    if len(prices) < 30:
        return []

    closes = [p.close for p in prices]
    highs = [p.high for p in prices]
    lows = [p.low for p in prices]
    volumes = [p.volume for p in prices]
    n = len(closes)
    last = n - 1

    atr_line = calc_atr(highs, lows, closes, 14)
    adx_line = calc_adx(highs, lows, closes, 14)
    stoch_k, stoch_d = calc_stochastic(highs, lows, closes, 14, 3)
    rsi_line = calc_rsi(closes, 14)
    vol_sma20 = calc_sma([float(v) for v in volumes], 20)
    sma5 = calc_sma(closes, 5)
    sma25 = calc_sma(closes, 25)
    macd_line, sig_line = calc_macd(closes)
    bb_upper, bb_middle, bb_lower = calc_bollinger_bands(closes)

    atr = atr_line[last]
    adx = adx_line[last]
    rsi = rsi_line[last]
    vol_ratio = (
        (volumes[last] / vol_sma20[last]) if vol_sma20[last] and vol_sma20[last] > 0 else None
    )

    k_last, k_prev = stoch_k[last], stoch_k[last - 1]
    d_last, d_prev = stoch_d[last], stoch_d[last - 1]
    stoch_cross_up = (
        all(v is not None for v in (k_prev, d_prev, k_last, d_last))
        and k_prev <= d_prev  # type: ignore[operator]
        and k_last > d_last  # type: ignore[operator]
    )

    sar_trend = calc_parabolic_sar(highs, lows)
    sar_bull = sar_trend[last] == "bull"

    kumo_top, kumo_bottom = calc_ichimoku_kumo(highs, lows, closes)
    price_above_kumo = kumo_top is not None and closes[last] > kumo_top
    price_below_kumo = kumo_bottom is not None and closes[last] < kumo_bottom

    macd_val = macd_line[last]
    sig_val = sig_line[last]
    histogram = (macd_val - sig_val) if (macd_val is not None and sig_val is not None) else None

    entry_price = closes[last]
    sl_mult = SL_ATR_MULTIPLIER_BEAR if market_regime == "bear" else SL_ATR_MULTIPLIER
    tp_mult = TP_ATR_MULTIPLIER_BULL if market_regime == "bull" else TP_ATR_MULTIPLIER

    snapshot = {
        "rsi": rsi, "sma5": sma5[last], "sma25": sma25[last],
        "macd": macd_val, "macd_signal": sig_val, "macd_histogram": histogram,
        "bb_upper": bb_upper[last], "bb_middle": bb_middle[last], "bb_lower": bb_lower[last],
        "atr": atr, "adx": adx, "stoch_k": k_last, "stoch_d": d_last,
        "volume": volumes[last], "volume_sma20": vol_sma20[last], "volume_ratio": vol_ratio,
        "market_regime": market_regime,
    }

    ctx = {
        "adx": adx, "stoch_cross_up": stoch_cross_up,
        "price_above_kumo": price_above_kumo, "price_below_kumo": price_below_kumo,
        "sar_bull": sar_bull, "volume_ratio": vol_ratio,
        "rsi": rsi, "market_regime": market_regime,
    }

    results: list[EvaluatedSignal] = []
    trend_strong_a = adx is not None and adx >= STRATEGY_A_ADX_MIN
    trend_strong_c = adx is not None and adx >= STRATEGY_C_ADX_MIN

    # Strategy A
    res_a = evaluate_strategy_a(prices) if STRATEGY_A_ENABLED else StrategyAResult(triggered=False)
    if res_a.triggered and trend_strong_a:
        from constants import STRATEGY_A_SL_ATR_MULT, STRATEGY_A_TP_ATR_MULT
        sl, tp = calc_risk_levels(entry_price, atr, sl_mult=STRATEGY_A_SL_ATR_MULT, tp_mult=STRATEGY_A_TP_ATR_MULT)
        score, grade = score_strategy_a(res_a, ctx)
        reason = _reason_a(res_a, adx)
        results.append(EvaluatedSignal("strategy_a", True, score, grade, entry_price, sl, tp, snapshot, reason))

    # Strategy B
    res_b = evaluate_strategy_b(prices) if STRATEGY_B_ENABLED else StrategyBResult(triggered=False)
    if res_b.triggered:
        from constants import STRATEGY_B_SL_ATR_MULT, STRATEGY_B_TP_ATR_MULT
        sl_b, tp_b_calc = calc_risk_levels(entry_price, atr, sl_mult=STRATEGY_B_SL_ATR_MULT, tp_mult=STRATEGY_B_TP_ATR_MULT)
        score, grade = score_strategy_b(res_b, ctx)
        reason = _reason_b(res_b)
        results.append(EvaluatedSignal("strategy_b", True, score, grade, entry_price, sl_b, tp_b_calc, snapshot, reason))

    # Strategy C
    res_c = evaluate_strategy_c(prices) if STRATEGY_C_ENABLED else StrategyCResult(triggered=False)
    if res_c.triggered and trend_strong_c:
        c_sl_mult = min(STRATEGY_C_SL_ATR_MULT, SL_ATR_MULTIPLIER_BEAR) if market_regime == "bear" else STRATEGY_C_SL_ATR_MULT
        c_tp_mult = max(STRATEGY_C_TP_ATR_MULT, TP_ATR_MULTIPLIER_BULL) if market_regime == "bull" else STRATEGY_C_TP_ATR_MULT
        sl_c, tp_c = calc_risk_levels(entry_price, atr, sl_mult=c_sl_mult, tp_mult=c_tp_mult)
        score, grade = score_strategy_c(res_c, ctx)
        reason = _reason_c(res_c)
        results.append(EvaluatedSignal("strategy_c", True, score, grade, entry_price, sl_c, tp_c, snapshot, reason))

    results.sort(key=lambda s: s.score, reverse=True)
    return results


def _reason_a(res: StrategyAResult, adx: float | None) -> str:
    parts = [
        f"{res.breakout_pct:+.1f}% breakout above 20d high" if res.new_high and res.breakout_pct is not None else "",
        "Above SMA50" if res.above_sma50 else "",
        f"Vol surge {res.volume_ratio:.1f}x" if res.volume_surge and res.volume_ratio else "",
        f"RSI {res.rsi:.1f}" if res.rsi else "",
        f"MACD hist +{res.macd_histogram:.2f}" if res.macd_histogram and res.macd_histogram > 0 else "",
    ]
    if adx is not None:
        parts.append(f"ADX {adx:.1f}")
    return " / ".join(p for p in parts if p)


def _reason_b(res: StrategyBResult) -> str:
    parts = [
        f"RSI {res.rsi:.1f} (deep oversold)" if res.deep_oversold and res.rsi else "",
        f"At BB lower ({res.bb_distance_pct:.1f}%)" if res.at_lower_bb and res.bb_distance_pct is not None else "",
        "Strong bullish reversal candle" if res.strong_reversal else "",
        "Above SMA200 (uptrend intact)" if res.above_sma200 else "",
        f"Volume spike {res.volume_ratio:.1f}x" if res.volume_spike and res.volume_ratio else "",
        "MACD improving" if res.macd_improving else "",
    ]
    return " / ".join(p for p in parts if p)


def _reason_c(res: StrategyCResult) -> str:
    parts = [
        f"SMA25 crossed SMA75 {res.gc_days_ago}d ago (Golden Cross)",
        f"RSI {res.rsi:.1f}" if res.rsi else "",
        f"MACD hist positive ({res.macd_histogram:.2f})" if res.macd_histogram else "",
    ]
    return " / ".join(p for p in parts if p)
