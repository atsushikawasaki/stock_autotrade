import { SL_ATR_MULTIPLIER, TP_ATR_MULTIPLIER } from '@/lib/constants';

export type RiskLevels = {
  stopLoss: number;
  takeProfit: number;
  riskRewardRatio: number;
};

export function calcRiskLevels(
  entryPrice: number,
  atr: number | null,
  tpOverride?: number,
  slMult?: number,
  tpMult?: number,
): RiskLevels | null {
  if (!atr || atr <= 0) return null;
  const slMultiplier = slMult ?? SL_ATR_MULTIPLIER;
  const tpMultiplier = tpMult ?? TP_ATR_MULTIPLIER;
  const sl = Math.round((entryPrice - slMultiplier * atr) * 10) / 10;
  const tp = tpOverride !== undefined
    ? Math.round(tpOverride * 10) / 10
    : Math.round((entryPrice + tpMultiplier * atr) * 10) / 10;
  const riskDist = entryPrice - sl;
  const rewardDist = tp - entryPrice;
  return {
    stopLoss: sl,
    takeProfit: tp,
    riskRewardRatio: riskDist > 0 ? rewardDist / riskDist : tpMultiplier / slMultiplier,
  };
}
