import type { StrategyAResult } from '@/lib/strategies/strategy-a';

type MarketRegime = 'bull' | 'bear' | 'neutral';
import type { StrategyBResult } from '@/lib/strategies/strategy-b';
import type { StrategyCResult } from '@/lib/strategies/strategy-c';
import {
  SCORE_A_GRADE_A_MIN, SCORE_A_GRADE_B_MIN, SCORE_A_GRADE_C_MIN,
  SCORE_B_GRADE_A_MIN, SCORE_B_GRADE_B_MIN, SCORE_B_GRADE_C_MIN,
  SCORE_C_GRADE_A_MIN, SCORE_C_GRADE_B_MIN, SCORE_C_GRADE_C_MIN,
  STRATEGY_B_LOW_VOL_THRESHOLD, STRATEGY_B_LOW_VOL_PENALTY,
  STRATEGY_C_BELOW_KUMO_PENALTY,
} from '@/lib/constants';
import type { SignalGrade } from '@/lib/types/database';

type ScoringContext = {
  adx: number | null;
  stochCrossUp: boolean;
  priceAboveKumo?: boolean;
  priceBelowKumo?: boolean;
  sarBull?: boolean;
  volumeRatio: number | null;
  rsi: number | null;
  macdHistogram: number | null;
  marketRegime: MarketRegime;
};

export type SignalScore = {
  score: number;
  grade: SignalGrade;
  breakdown: Record<string, number>;
};

export function scoreStrategyA(
  result: StrategyAResult,
  ctx: ScoringContext,
): SignalScore {
  const breakdown: Record<string, number> = {};
  let score = 0;

  if (!result.triggered) {
    return { score: 0, grade: 'D', breakdown: { base: 0 } };
  }

  breakdown.base = 50; score += 50;

  if (result.components.rsiCrossDaysAgo === 1) { breakdown.rsi_cross = 15; score += 15; }
  else if (result.components.rsiCrossDaysAgo === 2) { breakdown.rsi_cross = 10; score += 10; }

  if (result.components.volumeSurge) { breakdown.volume = 10; score += 10; }
  if (ctx.adx !== null && ctx.adx >= 25) { breakdown.adx = 10; score += 10; }
  if (ctx.marketRegime === 'bull') { breakdown.market = 10; score += 10; }
  if (ctx.marketRegime === 'bear') { breakdown.market = -20; score -= 20; }
  if (ctx.stochCrossUp) { breakdown.stoch = 5; score += 5; }

  score = Math.max(0, Math.min(100, score));
  return { score, grade: toGrade(score, SCORE_A_GRADE_A_MIN, SCORE_A_GRADE_B_MIN, SCORE_A_GRADE_C_MIN), breakdown };
}

export function scoreStrategyB(
  result: StrategyBResult,
  ctx: ScoringContext,
): SignalScore {
  const breakdown: Record<string, number> = {};
  let score = 0;

  if (!result.triggered) {
    return { score: 0, grade: 'D', breakdown: { base: 0 } };
  }

  breakdown.base = 55; score += 55;

  if (ctx.rsi !== null && ctx.rsi <= 25) { breakdown.rsi = 20; score += 20; }
  else if (ctx.rsi !== null && ctx.rsi <= 30) { breakdown.rsi = 15; score += 15; }
  else if (ctx.rsi !== null && ctx.rsi <= 35) { breakdown.rsi = 10; score += 10; }
  else if (ctx.rsi !== null && ctx.rsi <= 38) { breakdown.rsi = 5; score += 5; }

  if (result.components.macdImproving) { breakdown.macd = 10; score += 10; }
  if (ctx.volumeRatio !== null && ctx.volumeRatio >= 1.5) { breakdown.volume = 10; score += 10; }
  if (ctx.volumeRatio !== null && ctx.volumeRatio < STRATEGY_B_LOW_VOL_THRESHOLD) {
    breakdown.low_volume = STRATEGY_B_LOW_VOL_PENALTY; score += STRATEGY_B_LOW_VOL_PENALTY;
  }

  if (ctx.marketRegime === 'bull') { breakdown.market = 5; score += 5; }
  if (ctx.marketRegime === 'bear') { breakdown.market = -10; score -= 10; }
  if (ctx.stochCrossUp) { breakdown.stoch = 5; score += 5; }

  score = Math.max(0, Math.min(100, score));
  return { score, grade: toGrade(score, SCORE_B_GRADE_A_MIN, SCORE_B_GRADE_B_MIN, SCORE_B_GRADE_C_MIN), breakdown };
}

export function scoreStrategyC(
  result: StrategyCResult,
  ctx: ScoringContext,
): SignalScore {
  const breakdown: Record<string, number> = {};
  let score = 0;

  if (!result.triggered) {
    return { score: 0, grade: 'D', breakdown: { base: 0 } };
  }

  breakdown.base = 45; score += 45;

  if (result.components.gcDaysAgo === 1) { breakdown.gc_recency = 15; score += 15; }
  else if (result.components.gcDaysAgo === 2) { breakdown.gc_recency = 10; score += 10; }
  else if (result.components.gcDaysAgo === 3) { breakdown.gc_recency = 7; score += 7; }
  else { breakdown.gc_recency = 4; score += 4; }

  if (ctx.adx !== null && ctx.adx >= 25) { breakdown.adx = 10; score += 10; }
  if (ctx.marketRegime === 'bull') { breakdown.market = 10; score += 10; }
  if (ctx.marketRegime === 'bear') { breakdown.market = -20; score -= 20; }
  if (ctx.priceAboveKumo) { breakdown.ichimoku_kumo = 5; score += 5; }
  if (ctx.priceBelowKumo) { breakdown.ichimoku_below = STRATEGY_C_BELOW_KUMO_PENALTY; score += STRATEGY_C_BELOW_KUMO_PENALTY; }
  if (ctx.sarBull) { breakdown.sar_bull = 3; score += 3; }

  score = Math.max(0, Math.min(100, score));
  return { score, grade: toGrade(score, SCORE_C_GRADE_A_MIN, SCORE_C_GRADE_B_MIN, SCORE_C_GRADE_C_MIN), breakdown };
}

function toGrade(score: number, aMin: number, bMin: number, cMin: number): SignalGrade {
  if (score >= aMin) return 'A';
  if (score >= bMin) return 'B';
  if (score >= cMin) return 'C';
  return 'D';
}
