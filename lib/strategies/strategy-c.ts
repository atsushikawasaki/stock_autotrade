import { calcSMA, calcMACD, calcRSI } from '@/lib/indicators';
import type { PriceRow } from '@/lib/price-cache';
import { STRATEGY_C_GC_LOOKBACK, STRATEGY_C_RSI_MIN, STRATEGY_C_RSI_MAX } from '@/lib/constants';

export type StrategyCResult = {
  triggered: boolean;
  components: {
    /** SMA25 just crossed above SMA75 within lookback window */
    gcConfirmed: boolean;
    gcDaysAgo: number | null;
    /** MACD histogram is currently positive */
    macdPositive: boolean;
    /** RSI is in valid range (50–70): momentum without extreme overbought */
    rsiInRange: boolean;
    rsi: number | null;
    macdHistogram: number | null;
  };
};

// Re-export for external use (backtest engine)
export const GC_LOOKBACK_DAYS_DEFAULT = STRATEGY_C_GC_LOOKBACK;
export const RSI_C_MIN = STRATEGY_C_RSI_MIN;
export const RSI_C_MAX_DEFAULT = STRATEGY_C_RSI_MAX;

/**
 * Strategy C — SMA Golden Cross Momentum
 *
 * Triggered when:
 *   1. SMA25 just crossed above SMA75 within the last N days (fresh GC)
 *   2. MACD histogram is positive (trend strength confirmed)
 *   3. RSI is between 50–70 (momentum zone; not yet overbought)
 *
 * Rationale: Catches strong uptrend breakouts where RSI is already elevated
 * (never dips to 50 before the GC), which Strategy A misses because it
 * requires a fresh RSI cross above 50.
 *
 * Example: 三菱重工 7011 — SMA25 crossed SMA75 on 2026-01-20 while RSI was 68.
 * Strategy A fired no signal; Strategy C would detect the GC within 5 days.
 */
export function evaluateStrategyC(
  prices: PriceRow[],
  gcLookback = GC_LOOKBACK_DAYS_DEFAULT,
  rsiMax = RSI_C_MAX_DEFAULT,
): StrategyCResult {
  const n = prices.length;
  const empty: StrategyCResult = {
    triggered: false,
    components: {
      gcConfirmed: false, gcDaysAgo: null,
      macdPositive: false, rsiInRange: false,
      rsi: null, macdHistogram: null,
    },
  };
  if (n < 80) return empty;

  const closes = prices.map((p) => p.close);
  const sma25 = calcSMA(closes, 25);
  const sma75 = calcSMA(closes, 75);
  const { macd: macdLine, signal: signalLine } = calcMACD(closes);
  const rsiLine = calcRSI(closes, 14);

  const last = n - 1;

  // 1. SMA25 crossed above SMA75 within lookback window
  let gcConfirmed = false;
  let gcDaysAgo: number | null = null;
  for (let daysAgo = 1; daysAgo <= gcLookback; daysAgo++) {
    const i = last - daysAgo + 1;
    const prev = i - 1;
    if (prev < 0) break;
    const s25curr = sma25[i], s25prev = sma25[prev];
    const s75curr = sma75[i], s75prev = sma75[prev];
    if (s25curr !== null && s75curr !== null && s25prev !== null && s75prev !== null) {
      if (s25prev <= s75prev && s25curr > s75curr) {
        gcConfirmed = true;
        gcDaysAgo = daysAgo;
        break;
      }
    }
  }

  // 2. MACD histogram positive
  const macdLast = macdLine[last];
  const sigLast = signalLine[last];
  const histLast = macdLast !== null && sigLast !== null ? macdLast - sigLast : null;
  const macdPositive = histLast !== null && histLast > 0;

  // 3. RSI in momentum range (50–70)
  const rsi = rsiLine[last];
  const rsiInRange = rsi !== null && rsi >= RSI_C_MIN && rsi <= rsiMax;

  const triggered = gcConfirmed && macdPositive && rsiInRange;

  return {
    triggered,
    components: {
      gcConfirmed, gcDaysAgo,
      macdPositive, rsiInRange,
      rsi, macdHistogram: histLast,
    },
  };
}
