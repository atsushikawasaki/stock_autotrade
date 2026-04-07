import type { PriceRow } from '@/lib/price-cache';
import { calcATR } from '@/lib/indicators/atr';
import { calcADX } from '@/lib/indicators/adx';
import { calcStochastic } from '@/lib/indicators/stochastic';
import { calcBollingerBands } from '@/lib/indicators/bollinger-bands';
import { calcParabolicSAR } from '@/lib/indicators/parabolic-sar';
import { calcIchimoku } from '@/lib/indicators/ichimoku';
import { calcSMA, calcMACD, calcRSI } from '@/lib/indicators';
import { evaluateStrategyA } from './strategy-a';
import { evaluateStrategyB } from './strategy-b';
import { evaluateStrategyC } from './strategy-c';
import { scoreStrategyA, scoreStrategyB, scoreStrategyC } from '@/lib/signal-scorer';
import { calcRiskLevels } from '@/lib/risk-levels';
import type { MarketRegime } from '@/lib/market-filter';
import type { SignalIndicatorSnapshot, SignalStrategy, SignalGrade } from '@/lib/types/database';
import {
  STRATEGY_A_ADX_MIN,
  STRATEGY_C_SL_ATR_MULT, STRATEGY_C_TP_ATR_MULT,
  TP_ATR_MULTIPLIER_BULL, SL_ATR_MULTIPLIER_BEAR,
  SL_ATR_MULTIPLIER, TP_ATR_MULTIPLIER,
} from '@/lib/constants';

export type EvaluatedSignal = {
  strategy: SignalStrategy;
  triggered: boolean;
  score: number;
  grade: SignalGrade;
  entryPrice: number;
  stopLoss: number | null;
  takeProfit: number | null;
  indicators: SignalIndicatorSnapshot;
  reason: string;
};

export function evaluateAllStrategies(
  prices: PriceRow[],
  marketRegime: MarketRegime,
): EvaluatedSignal[] {
  if (prices.length < 30) return [];

  const closes = prices.map((p) => p.close);
  const highs = prices.map((p) => p.high ?? p.close);
  const lows = prices.map((p) => p.low ?? p.close);
  const volumes = prices.map((p) => p.volume);
  const n = closes.length;
  const last = n - 1;

  const atrLine = calcATR(highs, lows, closes, 14);
  const { adx: adxLine } = calcADX(highs, lows, closes, 14);
  const { k: stochK, d: stochD } = calcStochastic(highs, lows, closes, 14, 3);
  const rsiLine = calcRSI(closes, 14);
  const volSma20 = calcSMA(volumes, 20);
  const sma5Line = calcSMA(closes, 5);
  const sma25Line = calcSMA(closes, 25);
  const { macd: macdLine, signal: sigLine } = calcMACD(closes);
  const { upper, middle, lower } = calcBollingerBands(closes);

  const atr = atrLine[last];
  const adx = adxLine[last];
  const kLast = stochK[last];
  const kPrev = stochK[last - 1];
  const dLast = stochD[last];
  const dPrev = stochD[last - 1];
  const rsi = rsiLine[last];
  const volRatio =
    volSma20[last] !== null && volSma20[last]! > 0
      ? volumes[last] / volSma20[last]!
      : null;

  const stochCrossUp =
    kPrev !== null && dPrev !== null && kLast !== null && dLast !== null &&
    kPrev <= dPrev && kLast > dLast;

  // Parabolic SAR: bull = price above SAR (for Strategy C)
  const { trend: sarTrendArr } = calcParabolicSAR(highs, lows);
  const sarBull = sarTrendArr[last] === 'bull';

  // Ichimoku: price above Kumo (for Strategy C)
  const { senkouA: ichSpanA, senkouB: ichSpanB } = calcIchimoku(highs, lows, closes);
  const kumoIdx = last - 26;
  const spanA = kumoIdx >= 0 ? ichSpanA[kumoIdx + 26] : null;
  const spanB = kumoIdx >= 0 ? ichSpanB[kumoIdx + 26] : null;
  const kumoTop = spanA !== null && spanB !== null ? Math.max(spanA, spanB) : null;
  const kumoBottom = spanA !== null && spanB !== null ? Math.min(spanA, spanB) : null;
  const priceAboveKumo = kumoTop !== null && closes[last] > kumoTop;
  const priceBelowKumo = kumoBottom !== null && closes[last] < kumoBottom;

  const ctx = {
    adx, stochCrossUp, priceAboveKumo, priceBelowKumo, sarBull,
    volumeRatio: volRatio, rsi, macdHistogram: null as number | null, marketRegime,
  };

  const entryPrice = closes[last];

  // Regime-linked SL/TP multipliers
  const slMult = marketRegime === 'bear' ? SL_ATR_MULTIPLIER_BEAR : SL_ATR_MULTIPLIER;
  const tpMult = marketRegime === 'bull' ? TP_ATR_MULTIPLIER_BULL : TP_ATR_MULTIPLIER;
  const riskLevels = calcRiskLevels(entryPrice, atr, undefined, slMult, tpMult);

  // Strategy B target: BB middle (20-day SMA)
  const bbMiddle = middle[last];
  const riskLevelsB = bbMiddle !== null && bbMiddle > entryPrice
    ? calcRiskLevels(entryPrice, atr, bbMiddle, slMult)
    : riskLevels;

  // Strategy C: wider SL
  const cSlFinal = marketRegime === 'bear' ? Math.min(STRATEGY_C_SL_ATR_MULT, SL_ATR_MULTIPLIER_BEAR) : STRATEGY_C_SL_ATR_MULT;
  const cTpFinal = marketRegime === 'bull' ? Math.max(STRATEGY_C_TP_ATR_MULT, TP_ATR_MULTIPLIER_BULL) : STRATEGY_C_TP_ATR_MULT;
  const riskLevelsC = calcRiskLevels(entryPrice, atr, undefined, cSlFinal, cTpFinal);

  const macdVal = macdLine[last];
  const sigVal = sigLine[last];
  const histogram = macdVal !== null && sigVal !== null ? macdVal - sigVal : null;

  const snapshot: SignalIndicatorSnapshot = {
    rsi,
    sma5: sma5Line[last],
    sma25: sma25Line[last],
    macd: macdVal,
    macd_signal: sigVal,
    macd_histogram: histogram,
    bb_upper: upper[last],
    bb_middle: middle[last],
    bb_lower: lower[last],
    atr,
    adx,
    stoch_k: kLast,
    stoch_d: dLast,
    volume: volumes[last],
    volume_sma20: volSma20[last],
    volume_ratio: volRatio,
    market_regime: marketRegime,
  };

  const results: EvaluatedSignal[] = [];

  // Strategy A: suppress when ADX too low
  const trendStrong = adx !== null && adx >= STRATEGY_A_ADX_MIN;

  const resA = evaluateStrategyA(prices);
  if (resA.triggered && trendStrong) {
    const { score, grade } = scoreStrategyA(resA, ctx);
    const reason = buildStrategyAReason(resA, adx);
    results.push({
      strategy: 'strategy_a',
      triggered: true,
      score,
      grade,
      entryPrice,
      stopLoss: riskLevels?.stopLoss ?? null,
      takeProfit: riskLevels?.takeProfit ?? null,
      indicators: snapshot,
      reason,
    });
  }

  const resB = evaluateStrategyB(prices);
  if (resB.triggered) {
    const { score, grade } = scoreStrategyB(resB, ctx);
    const reason = buildStrategyBReason(resB);
    results.push({
      strategy: 'strategy_b',
      triggered: true,
      score,
      grade,
      entryPrice,
      stopLoss: riskLevelsB?.stopLoss ?? null,
      takeProfit: riskLevelsB?.takeProfit ?? null,
      indicators: snapshot,
      reason,
    });
  }

  const resC = evaluateStrategyC(prices);
  if (resC.triggered && trendStrong) {
    const { score, grade } = scoreStrategyC(resC, ctx);
    const reason = buildStrategyCReason(resC);
    results.push({
      strategy: 'strategy_c',
      triggered: true,
      score,
      grade,
      entryPrice,
      stopLoss: riskLevelsC?.stopLoss ?? null,
      takeProfit: riskLevelsC?.takeProfit ?? null,
      indicators: snapshot,
      reason,
    });
  }

  return results.sort((a, b) => b.score - a.score);
}

function buildStrategyAReason(res: ReturnType<typeof evaluateStrategyA>, adx: number | null): string {
  const { rsiCrossDaysAgo, rsi, macdHistogram } = res.components;
  const parts = [
    `SMA25>SMA75 trend confirmed`,
    `RSI crossed 50 ${rsiCrossDaysAgo} day(s) ago (now ${rsi?.toFixed(1) ?? '-'})`,
    `MACD histogram positive (${macdHistogram !== null ? macdHistogram.toFixed(2) : '-'})`,
  ];
  if (adx !== null) parts.push(`ADX ${adx.toFixed(1)} (${adx >= 25 ? 'strong' : 'moderate'})`);
  return parts.join(' / ');
}

function buildStrategyBReason(res: ReturnType<typeof evaluateStrategyB>): string {
  const { rsi, bbDistancePct, macdImproving } = res.components;
  const parts = [
    `Near BB lower (${bbDistancePct?.toFixed(1) ?? '-'}% away)`,
    `RSI ${rsi?.toFixed(1) ?? '-'} (oversold)`,
    `Bullish candle confirmed`,
  ];
  if (macdImproving) parts.push(`MACD histogram improving`);
  return parts.join(' / ');
}

function buildStrategyCReason(res: ReturnType<typeof evaluateStrategyC>): string {
  const { gcDaysAgo, rsi, macdHistogram } = res.components;
  const parts = [
    `SMA25 crossed above SMA75 ${gcDaysAgo} day(s) ago (Golden Cross)`,
    `RSI ${rsi?.toFixed(1) ?? '-'} (momentum confirmed)`,
    `MACD histogram positive (${macdHistogram !== null ? macdHistogram.toFixed(2) : '-'})`,
  ];
  return parts.join(' / ');
}
