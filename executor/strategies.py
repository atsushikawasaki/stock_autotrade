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
    STRATEGY_A_RSI_CROSS_LEVEL,
    STRATEGY_A_RSI_CROSS_LOOKBACK,
    STRATEGY_A_RSI_MIN_AT_SIGNAL,
    STRATEGY_A_MACD_HIST_MAX_RATIO,
    STRATEGY_A_VOLUME_RATIO_MIN,
    STRATEGY_A_ADX_MIN,
    STRATEGY_B_RSI_THRESHOLD,
    STRATEGY_B_BB_PROXIMITY_PCT,
    STRATEGY_B_BB_BANDWIDTH_MAX,
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
    triggered: bool
    rsi_cross_up: bool = False
    rsi_cross_days_ago: int | None = None
    macd_positive: bool = False
    macd_not_extended: bool = False
    trend_confirmed: bool = False
    rsi_above_min: bool = False
    volume_surge: bool = False
    rsi: float | None = None
    volume_ratio: float | None = None
    macd_histogram: float | None = None


@dataclass(frozen=True)
class StrategyBResult:
    triggered: bool
    at_lower_bb: bool = False
    rsi_oversold: bool = False
    bullish_candle: bool = False
    bandwidth_ok: bool = False
    macd_improving: bool = False
    rsi: float | None = None
    bb_distance_pct: float | None = None
    bb_bandwidth: float | None = None
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
    n = len(prices)
    if n < 80:
        return StrategyAResult(triggered=False)

    closes = [p.close for p in prices]
    volumes = [p.volume for p in prices]

    sma25 = calc_sma(closes, 25)
    sma75 = calc_sma(closes, 75)
    macd_line, signal_line = calc_macd(closes)
    rsi_line = calc_rsi(closes, 14)
    vol_sma20 = calc_sma([float(v) for v in volumes], 20)

    last = n - 1

    trend_confirmed = (
        sma25[last] is not None and sma75[last] is not None and sma25[last] > sma75[last]
    )

    rsi_cross_up = False
    rsi_cross_days_ago: int | None = None
    for days_ago in range(1, STRATEGY_A_RSI_CROSS_LOOKBACK + 1):
        i = last - days_ago + 1
        prev = i - 1
        if prev < 0:
            break
        r_curr = rsi_line[i]
        r_prev = rsi_line[prev]
        if r_curr is not None and r_prev is not None:
            if r_prev <= STRATEGY_A_RSI_CROSS_LEVEL < r_curr:
                rsi_cross_up = True
                rsi_cross_days_ago = days_ago
                break

    rsi = rsi_line[last]
    rsi_above_min = rsi is not None and rsi >= STRATEGY_A_RSI_MIN_AT_SIGNAL

    macd_val = macd_line[last]
    sig_val = signal_line[last]
    hist = (macd_val - sig_val) if (macd_val is not None and sig_val is not None) else None
    macd_positive = hist is not None and hist > 0
    macd_not_extended = (
        hist is not None and closes[last] > 0 and abs(hist) / closes[last] <= STRATEGY_A_MACD_HIST_MAX_RATIO
    )

    vol_ratio = (
        (volumes[last] / vol_sma20[last]) if vol_sma20[last] and vol_sma20[last] > 0 else None
    )
    volume_surge = vol_ratio is not None and vol_ratio >= STRATEGY_A_VOLUME_RATIO_MIN

    triggered = trend_confirmed and rsi_cross_up and rsi_above_min and macd_positive and macd_not_extended

    return StrategyAResult(
        triggered=triggered,
        rsi_cross_up=rsi_cross_up,
        rsi_cross_days_ago=rsi_cross_days_ago,
        macd_positive=macd_positive,
        macd_not_extended=macd_not_extended,
        trend_confirmed=trend_confirmed,
        rsi_above_min=rsi_above_min,
        volume_surge=volume_surge,
        rsi=rsi,
        volume_ratio=vol_ratio,
        macd_histogram=hist,
    )


def evaluate_strategy_b(prices: list[PriceRow]) -> StrategyBResult:
    n = len(prices)
    if n < 25:
        return StrategyBResult(triggered=False)

    closes = [p.close for p in prices]
    upper, middle, lower = calc_bollinger_bands(closes, 20, 2)
    macd_line, signal_line = calc_macd(closes)
    rsi_line = calc_rsi(closes, 14)

    last = n - 1
    curr_close = closes[last]
    curr_open = prices[last].open
    curr_upper = upper[last]
    curr_middle = middle[last]
    curr_lower = lower[last]

    bb_dist_pct: float | None = None
    if curr_lower is not None and curr_lower > 0:
        bb_dist_pct = ((curr_close - curr_lower) / curr_lower) * 100
    at_lower_bb = bb_dist_pct is not None and bb_dist_pct <= STRATEGY_B_BB_PROXIMITY_PCT

    rsi = rsi_line[last]
    rsi_oversold = rsi is not None and rsi <= STRATEGY_B_RSI_THRESHOLD

    bullish_candle = curr_close > curr_open

    bb_bandwidth: float | None = None
    if curr_upper is not None and curr_lower is not None and curr_middle is not None and curr_middle > 0:
        bb_bandwidth = (curr_upper - curr_lower) / curr_middle
    bandwidth_ok = bb_bandwidth is not None and bb_bandwidth <= STRATEGY_B_BB_BANDWIDTH_MAX

    macd_last = macd_line[last]
    sig_last = signal_line[last]
    macd_prev = macd_line[last - 1]
    sig_prev = signal_line[last - 1]
    hist_last = (macd_last - sig_last) if (macd_last is not None and sig_last is not None) else None
    hist_prev = (macd_prev - sig_prev) if (macd_prev is not None and sig_prev is not None) else None
    macd_improving = hist_last is not None and hist_prev is not None and hist_last > hist_prev

    triggered = at_lower_bb and rsi_oversold and bullish_candle and bandwidth_ok

    return StrategyBResult(
        triggered=triggered,
        at_lower_bb=at_lower_bb,
        rsi_oversold=rsi_oversold,
        bullish_candle=bullish_candle,
        bandwidth_ok=bandwidth_ok,
        macd_improving=macd_improving,
        rsi=rsi,
        bb_distance_pct=bb_dist_pct,
        bb_bandwidth=bb_bandwidth,
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
    trend_strong = adx is not None and adx >= STRATEGY_A_ADX_MIN

    # Strategy A
    res_a = evaluate_strategy_a(prices)
    if res_a.triggered and trend_strong:
        sl, tp = calc_risk_levels(entry_price, atr, sl_mult=sl_mult, tp_mult=tp_mult)
        score, grade = score_strategy_a(res_a, ctx)
        reason = _reason_a(res_a, adx)
        results.append(EvaluatedSignal("strategy_a", True, score, grade, entry_price, sl, tp, snapshot, reason))

    # Strategy B
    res_b = evaluate_strategy_b(prices)
    if res_b.triggered:
        bb_mid = bb_middle[last]
        tp_b = round(bb_mid, 2) if bb_mid is not None and bb_mid > entry_price else None
        sl_b, tp_b_calc = calc_risk_levels(entry_price, atr, tp_override=tp_b, sl_mult=2.0)
        score, grade = score_strategy_b(res_b, ctx)
        reason = _reason_b(res_b)
        results.append(EvaluatedSignal("strategy_b", True, score, grade, entry_price, sl_b, tp_b_calc, snapshot, reason))

    # Strategy C
    res_c = evaluate_strategy_c(prices)
    if res_c.triggered and trend_strong:
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
        "SMA25>SMA75 trend confirmed",
        f"RSI crossed 50 {res.rsi_cross_days_ago}d ago (now {res.rsi:.1f})" if res.rsi else "",
        f"MACD hist positive ({res.macd_histogram:.2f})" if res.macd_histogram else "",
    ]
    if adx is not None:
        parts.append(f"ADX {adx:.1f} ({'strong' if adx >= 25 else 'moderate'})")
    return " / ".join(p for p in parts if p)


def _reason_b(res: StrategyBResult) -> str:
    parts = [
        f"Near BB lower ({res.bb_distance_pct:.1f}% away)" if res.bb_distance_pct is not None else "",
        f"RSI {res.rsi:.1f} (oversold)" if res.rsi else "",
        "Bullish candle",
    ]
    if res.macd_improving:
        parts.append("MACD improving")
    return " / ".join(p for p in parts if p)


def _reason_c(res: StrategyCResult) -> str:
    parts = [
        f"SMA25 crossed SMA75 {res.gc_days_ago}d ago (Golden Cross)",
        f"RSI {res.rsi:.1f}" if res.rsi else "",
        f"MACD hist positive ({res.macd_histogram:.2f})" if res.macd_histogram else "",
    ]
    return " / ".join(p for p in parts if p)
