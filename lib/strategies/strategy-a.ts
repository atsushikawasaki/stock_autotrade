import { calcSMA, calcMACD, calcRSI } from '@/lib/indicators';
import type { PriceRow } from '@/lib/price-cache';
import {
  STRATEGY_A_RSI_CROSS_LEVEL,
  STRATEGY_A_RSI_CROSS_LOOKBACK,
  STRATEGY_A_RSI_MIN_AT_SIGNAL,
  STRATEGY_A_MACD_HIST_MAX_RATIO,
  STRATEGY_A_VOLUME_RATIO_MIN,
} from '@/lib/constants';

export type StrategyAResult = {
  triggered: boolean;
  components: {
    /** RSI crossed above STRATEGY_A_RSI_CROSS_LEVEL within lookback window */
    rsiCrossUp: boolean;
    rsiCrossDaysAgo: number | null;
    /** MACD histogram is currently positive (MACD above signal line) */
    macdPositive: boolean;
    /** MACD histogram is not over-extended (histogram/close <= STRATEGY_A_MACD_HIST_MAX_RATIO) */
    macdNotExtended: boolean;
    /** SMA25 > SMA75: medium-term uptrend confirmed (filters dead-cat bounces) */
    trendConfirmed: boolean;
    /** RSI at evaluation time is above minimum threshold (avoids borderline 50-line stalls) */
    rsiAboveMin: boolean;
    volumeSurge: boolean;
    rsi: number | null;
    volumeRatio: number | null;
    macdHistogram: number | null;
  };
};

/**
 * Strategy A — RSI Momentum Crossover in Confirmed Uptrend
 *
 * Triggered when ALL of the following are met:
 *   1. SMA25 > SMA75 (medium-term uptrend confirmed — filters dead-cat bounces)
 *   2. RSI crossed above 50 within the last N days (momentum awakening)
 *   3. RSI at evaluation ≥ STRATEGY_A_RSI_MIN_AT_SIGNAL (avoids borderline stalls at 50-line)
 *   4. MACD histogram is positive (trend confirmation, not just improving)
 *   5. MACD histogram / close ≤ STRATEGY_A_MACD_HIST_MAX_RATIO (momentum not already exhausted)
 *
 * Key tuning decisions from backtest analysis (1yr, 78 stocks):
 *   - RSI 50-55 at signal → 44.4% win / -0.59% avg. Requiring RSI ≥ 53 removes these borderline cases.
 *   - Losing trades had avg MACD histogram 12.68 vs 6.10 for winners. An over-extended MACD means
 *     the move is already priced in; capping histogram prevents chasing.
 *   - RSI lookback reduced 3→2 days: day-3 crosses = 47.1% win, worst age bucket.
 *   - ADX filtering (20-27 cap) is applied in the backtest engine, not here.
 *
 * Rationale: Requiring SMA25 > SMA75 eliminates false signals in downtrending
 * stocks where RSI bounces off oversold are temporary. RSI cross-50 is a
 * leading momentum signal; MACD > 0 confirms trend direction.
 */
export function evaluateStrategyA(prices: PriceRow[]): StrategyAResult {
  const n = prices.length;
  const empty: StrategyAResult = {
    triggered: false,
    components: {
      rsiCrossUp: false, rsiCrossDaysAgo: null,
      macdPositive: false, macdNotExtended: false,
      trendConfirmed: false, rsiAboveMin: false,
      volumeSurge: false, rsi: null, volumeRatio: null, macdHistogram: null,
    },
  };
  if (n < 80) return empty; // Need 75+ days for SMA75

  const closes = prices.map((p) => p.close);
  const volumes = prices.map((p) => p.volume);

  const sma25 = calcSMA(closes, 25);
  const sma75 = calcSMA(closes, 75);
  const { macd: macdLine, signal: signalLine } = calcMACD(closes);
  const rsiLine = calcRSI(closes, 14);
  const volSma20 = calcSMA(volumes, 20);

  const last = n - 1;

  // 1. SMA25 > SMA75: medium-term uptrend confirmed
  const trendConfirmed = sma25[last] !== null && sma75[last] !== null
    && sma25[last]! > sma75[last]!;

  // 2. RSI crossed above RSI_CROSS_LEVEL within lookback window
  let rsiCrossUp = false;
  let rsiCrossDaysAgo: number | null = null;
  for (let daysAgo = 1; daysAgo <= STRATEGY_A_RSI_CROSS_LOOKBACK; daysAgo++) {
    const i = last - daysAgo + 1;
    const prev = i - 1;
    if (prev < 0) break;
    const rCurr = rsiLine[i];
    const rPrev = rsiLine[prev];
    if (rCurr !== null && rPrev !== null) {
      if (rPrev <= STRATEGY_A_RSI_CROSS_LEVEL && rCurr > STRATEGY_A_RSI_CROSS_LEVEL) {
        rsiCrossUp = true;
        rsiCrossDaysAgo = daysAgo;
        break;
      }
    }
  }

  // 3. RSI at evaluation time must be above minimum threshold
  const rsi = rsiLine[last];
  const rsiAboveMin = rsi !== null && rsi >= STRATEGY_A_RSI_MIN_AT_SIGNAL;

  // 4. MACD histogram positive
  const macdLast = macdLine[last];
  const sigLast = signalLine[last];
  const histLast = macdLast !== null && sigLast !== null ? macdLast - sigLast : null;
  const macdPositive = histLast !== null && histLast > 0;

  // 5. MACD histogram not over-extended (histogram/close <= max ratio)
  const currClose = closes[last];
  const macdNotExtended = histLast !== null && currClose > 0
    ? Math.abs(histLast) / currClose <= STRATEGY_A_MACD_HIST_MAX_RATIO
    : false;

  // Volume surge (scoring only — not a hard gate)
  const volLast = volumes[last];
  const volSmaLast = volSma20[last];
  const volumeRatio = volSmaLast !== null && volSmaLast > 0 ? volLast / volSmaLast : null;
  const volumeSurge = volumeRatio !== null && volumeRatio >= STRATEGY_A_VOLUME_RATIO_MIN;

  const triggered = trendConfirmed && rsiCrossUp && rsiAboveMin && macdPositive && macdNotExtended;

  return {
    triggered,
    components: {
      rsiCrossUp, rsiCrossDaysAgo,
      macdPositive, macdNotExtended,
      trendConfirmed, rsiAboveMin,
      volumeSurge, rsi, volumeRatio, macdHistogram: histLast,
    },
  };
}
