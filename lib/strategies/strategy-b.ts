import { calcRSI, calcMACD } from '@/lib/indicators';
import { calcBollingerBands } from '@/lib/indicators/bollinger-bands';
import type { PriceRow } from '@/lib/price-cache';
import {
  STRATEGY_B_RSI_THRESHOLD,
  STRATEGY_B_BB_PROXIMITY_PCT,
  STRATEGY_B_BB_BANDWIDTH_MAX,
} from '@/lib/constants';

export type StrategyBResult = {
  triggered: boolean;
  components: {
    /** Price is at or within STRATEGY_B_BB_PROXIMITY_PCT% of lower BB */
    atLowerBB: boolean;
    /** RSI is deeply oversold (≤ STRATEGY_B_RSI_THRESHOLD) */
    rsiOversold: boolean;
    /** Signal day candle is bullish (close > open) — buyers stepping in */
    bullishCandle: boolean;
    /** BB bands are not expanding rapidly — range-bound conditions */
    bandwidthOk: boolean;
    /** MACD histogram improving — used for scoring only, NOT a hard gate */
    macdImproving: boolean;
    rsi: number | null;
    /** % distance from lower BB (negative = below, 0 = at, positive = above) */
    bbDistancePct: number | null;
    /** BB bandwidth = (upper − lower) / middle */
    bbBandwidth: number | null;
    macdHistogram: number | null;
  };
};

/**
 * Strategy B — BB Lower Touch + Deep Oversold Reversal
 *
 * Triggered when ALL of the following are met:
 *   1. Price is at or within 3% above the lower Bollinger Band (proximity)
 *   2. RSI ≤ 40 (oversold, not merely weak)
 *   3. Signal day candle is bullish: close > open (reversal started, not still falling)
 *   4. BB bandwidth (upper−lower)/middle ≤ 12% (bands not expanding = not trending)
 *
 * Rationale:
 *   - BB lower touch + RSI oversold = setup (necessary but not sufficient)
 *   - Bullish candle = execution filter: buyers are stepping in on this day,
 *     eliminating "knife-catching" where price is still falling through the band
 *   - Bandwidth filter: when bands are expanding rapidly, it signals a trending
 *     market where mean-reversion targets (BB middle) are unreliable
 *   - MACD improvement retained as scoring bonus only (lags at reversal points)
 */
export function evaluateStrategyB(prices: PriceRow[]): StrategyBResult {
  const n = prices.length;
  const empty: StrategyBResult = {
    triggered: false,
    components: {
      atLowerBB: false, rsiOversold: false, bullishCandle: false,
      bandwidthOk: false, macdImproving: false,
      rsi: null, bbDistancePct: null, bbBandwidth: null, macdHistogram: null,
    },
  };
  if (n < 25) return empty;

  const closes = prices.map((p) => p.close);
  const { upper, middle, lower } = calcBollingerBands(closes, 20, 2);
  const { macd: macdLine, signal: signalLine } = calcMACD(closes);
  const rsiLine = calcRSI(closes, 14);

  const last = n - 1;
  const currClose = closes[last];
  const currOpen = prices[last].open;
  const currUpper = upper[last];
  const currMiddle = middle[last];
  const currLower = lower[last];

  // 1. Price at or within PROXIMITY% above lower BB
  let bbDistancePct: number | null = null;
  if (currLower !== null && currLower > 0) {
    bbDistancePct = ((currClose - currLower) / currLower) * 100;
  }
  const atLowerBB = bbDistancePct !== null && bbDistancePct <= STRATEGY_B_BB_PROXIMITY_PCT;

  // 2. RSI oversold
  const rsi = rsiLine[last];
  const rsiOversold = rsi !== null && rsi <= STRATEGY_B_RSI_THRESHOLD;

  // 3. Bullish candle: close > open (buyers stepping in, not still falling)
  const bullishCandle = currOpen !== null ? currClose > currOpen : false;

  // 4. BB bandwidth check: (upper − lower) / middle ≤ threshold
  let bbBandwidth: number | null = null;
  if (currUpper !== null && currLower !== null && currMiddle !== null && currMiddle > 0) {
    bbBandwidth = (currUpper - currLower) / currMiddle;
  }
  const bandwidthOk = bbBandwidth !== null && bbBandwidth <= STRATEGY_B_BB_BANDWIDTH_MAX;

  // MACD histogram improving (scoring bonus only)
  const macdLast = macdLine[last];
  const sigLast = signalLine[last];
  const macdPrev = macdLine[last - 1];
  const sigPrev = signalLine[last - 1];
  const histLast = macdLast !== null && sigLast !== null ? macdLast - sigLast : null;
  const histPrev = macdPrev !== null && sigPrev !== null ? macdPrev - sigPrev : null;
  const macdImproving = histLast !== null && histPrev !== null && histLast > histPrev;

  const triggered = atLowerBB && rsiOversold && bullishCandle && bandwidthOk;

  return {
    triggered,
    components: {
      atLowerBB, rsiOversold, bullishCandle, bandwidthOk, macdImproving,
      rsi, bbDistancePct, bbBandwidth, macdHistogram: histLast,
    },
  };
}
