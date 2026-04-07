"""Technical indicators — direct port from TypeScript lib/indicators*.ts"""

from __future__ import annotations

import numpy as np


def calc_sma(values: list[float], period: int) -> list[float | None]:
    """Simple Moving Average."""
    result: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1 : i + 1]) / period
    return result


def calc_ema(values: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average."""
    k = 2 / (period + 1)
    result: list[float | None] = [None] * len(values)
    prev: float | None = None
    for i in range(len(values)):
        if i < period - 1:
            continue
        if i == period - 1:
            seed = sum(values[:period]) / period
            result[i] = seed
            prev = seed
        elif prev is not None:
            ema = values[i] * k + prev * (1 - k)
            result[i] = ema
            prev = ema
    return result


def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[list[float | None], list[float | None]]:
    """MACD line and signal line."""
    fast_ema = calc_ema(closes, fast)
    slow_ema = calc_ema(closes, slow)

    macd_line: list[float | None] = [
        (f - s if f is not None and s is not None else None)
        for f, s in zip(fast_ema, slow_ema)
    ]

    macd_not_null = [v for v in macd_line if v is not None]
    signal_of_macd = calc_ema(macd_not_null, signal_period)

    signal: list[float | None] = [None] * len(closes)
    idx = 0
    for i in range(len(closes)):
        if macd_line[i] is not None:
            signal[i] = signal_of_macd[idx] if idx < len(signal_of_macd) else None
            idx += 1

    return macd_line, signal


def calc_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Relative Strength Index."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        if change > 0:
            avg_gain += change
        else:
            avg_loss += abs(change)
    avg_gain /= period
    avg_loss /= period

    result[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    for i in range(period + 1, n):
        change = closes[i] - closes[i - 1]
        gain = change if change > 0 else 0
        loss = abs(change) if change < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    return result


def calc_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """Average True Range."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i] - closes[i - 1])
        tr.append(max(hl, hpc, lpc))

    atr = sum(tr[1 : period + 1]) / period
    result[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + tr[i]) / period
        result[i] = atr

    return result


def calc_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """Average Directional Index (ADX only)."""
    n = len(closes)
    adx: list[float | None] = [None] * n
    if n < period * 2 + 1:
        return adx

    raw_plus_dm = [0.0] * n
    raw_minus_dm = [0.0] * n
    tr = [0.0] * n

    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        raw_plus_dm[i] = up if (up > down and up > 0) else 0
        raw_minus_dm[i] = down if (down > up and down > 0) else 0
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hpc, lpc)

    smooth_tr = sum(tr[1 : period + 1])
    smooth_plus = sum(raw_plus_dm[1 : period + 1])
    smooth_minus = sum(raw_minus_dm[1 : period + 1])

    dx_buffer: list[float] = []

    for i in range(period, n):
        if i > period:
            smooth_tr = smooth_tr - smooth_tr / period + tr[i]
            smooth_plus = smooth_plus - smooth_plus / period + raw_plus_dm[i]
            smooth_minus = smooth_minus - smooth_minus / period + raw_minus_dm[i]

        pdi = (smooth_plus / smooth_tr * 100) if smooth_tr != 0 else 0
        mdi = (smooth_minus / smooth_tr * 100) if smooth_tr != 0 else 0
        di_sum = pdi + mdi
        dx = (abs(pdi - mdi) / di_sum * 100) if di_sum != 0 else 0
        dx_buffer.append(dx)

        if len(dx_buffer) == period:
            adx[i] = sum(dx_buffer) / period
        elif len(dx_buffer) > period:
            adx[i] = (adx[i - 1] * (period - 1) + dx) / period  # type: ignore[operator]

    return adx


def calc_bollinger_bands(
    closes: list[float], period: int = 20, std_mult: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Bollinger Bands → (upper, middle, lower)."""
    middle = calc_sma(closes, period)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)

    for i in range(period - 1, len(closes)):
        sl = closes[i - period + 1 : i + 1]
        mean = middle[i]  # type: ignore[arg-type]
        variance = sum((v - mean) ** 2 for v in sl) / period  # type: ignore[operator]
        sd = variance**0.5
        upper[i] = mean + std_mult * sd  # type: ignore[operator]
        lower[i] = mean - std_mult * sd  # type: ignore[operator]

    return upper, middle, lower


def calc_stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[list[float | None], list[float | None]]:
    """Stochastic %K and %D."""
    n = len(closes)
    raw_k: list[float | None] = [None] * n

    for i in range(k_period - 1, n):
        h_slice = highs[i - k_period + 1 : i + 1]
        l_slice = lows[i - k_period + 1 : i + 1]
        highest = max(h_slice)
        lowest = min(l_slice)
        rng = highest - lowest
        raw_k[i] = 50.0 if rng == 0 else ((closes[i] - lowest) / rng) * 100

    k_vals = [v for v in raw_k if v is not None]
    d_of_k = calc_sma(k_vals, d_period)

    d: list[float | None] = [None] * n
    idx = 0
    for i in range(n):
        if raw_k[i] is not None:
            d[i] = d_of_k[idx] if idx < len(d_of_k) else None
            idx += 1

    return raw_k, d


def calc_parabolic_sar(
    highs: list[float], lows: list[float], af_step: float = 0.02, af_max: float = 0.20
) -> list[str | None]:
    """Parabolic SAR → trend list ('bull' | 'bear' | None)."""
    n = len(highs)
    trend: list[str | None] = [None] * n
    if n < 2:
        return trend

    is_bull = highs[1] >= highs[0]
    af = af_step
    ep = highs[1] if is_bull else lows[1]
    prev_sar = min(lows[0], lows[1]) if is_bull else max(highs[0], highs[1])

    trend[1] = "bull" if is_bull else "bear"

    for i in range(2, n):
        new_sar = prev_sar + af * (ep - prev_sar)

        if is_bull:
            new_sar = min(new_sar, lows[i - 1], lows[i - 2])
            if lows[i] < new_sar:
                is_bull = False
                new_sar = ep
                ep = lows[i]
                af = af_step
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + af_step, af_max)
        else:
            new_sar = max(new_sar, highs[i - 1], highs[i - 2])
            if highs[i] > new_sar:
                is_bull = True
                new_sar = ep
                ep = highs[i]
                af = af_step
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + af_step, af_max)

        trend[i] = "bull" if is_bull else "bear"
        prev_sar = new_sar

    return trend


def calc_ichimoku_kumo(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    tenkan_p: int = 9,
    kijun_p: int = 26,
    senkou_b_p: int = 52,
    displacement: int = 26,
) -> tuple[float | None, float | None]:
    """Returns (kumoTop, kumoBottom) at the current bar position."""
    n = len(closes)
    if n < senkou_b_p + displacement:
        return None, None

    def midpoint(end: int, period: int) -> float | None:
        start = end - period + 1
        if start < 0:
            return None
        return (max(highs[start : end + 1]) + min(lows[start : end + 1])) / 2

    last = n - 1
    kumo_idx = last - displacement
    if kumo_idx < 0:
        return None, None

    tenkan = midpoint(kumo_idx, tenkan_p)
    kijun = midpoint(kumo_idx, kijun_p)
    span_a = ((tenkan + kijun) / 2) if (tenkan is not None and kijun is not None) else None
    span_b = midpoint(kumo_idx, senkou_b_p)

    if span_a is not None and span_b is not None:
        return max(span_a, span_b), min(span_a, span_b)
    return None, None
