import { calcSMA } from '@/lib/indicators';
import { calcATR } from '@/lib/indicators/atr';
import type { PriceRow } from '@/lib/price-cache';
import type { Signal, ExitReason, PositionMeta } from '@/lib/types/database';
import {
  MAX_HOLDING_DAYS_A,
  MAX_HOLDING_DAYS_B,
  MAX_HOLDING_DAYS_B_BULL,
  MAX_HOLDING_DAYS_C,
  TRAIL_STOP_ATR_MULTIPLIER,
  PARTIAL_EXIT_RATIO,
  MA_CROSS_CONFIRM_DAYS_BULL,
  MA_CROSS_CONFIRM_DAYS_BEAR,
  STRATEGY_A_MA_CROSS_CONFIRM_DAYS,
  STRATEGY_C_PARTIAL_EXIT_RATIO,
  STRATEGY_C_TRAIL_ATR_MULT,
} from '@/lib/constants';

export type ExitEvent = {
  type: ExitReason;
  exitPrice: number;
  returnPct: number;
  blendedReturnPct?: number;
  holdingDays: number;
  updatedMeta?: PositionMeta;
};

function calcHoldingDays(signalDate: string, today: string): number {
  return Math.floor(
    (new Date(today).getTime() - new Date(signalDate).getTime()) / (1000 * 60 * 60 * 24)
  );
}

function isMACrossDown(
  closes: number[],
  sma5: (number | null)[],
  sma25: (number | null)[],
  confirmDays: number = STRATEGY_A_MA_CROSS_CONFIRM_DAYS,
): boolean {
  const last = closes.length - 1;
  if (last < confirmDays) return false;
  for (let i = 0; i < confirmDays; i++) {
    const idx = last - i;
    const s5 = sma5[idx];
    const s25 = sma25[idx];
    if (s5 === null || s25 === null || s5 >= s25) return false;
  }
  return true;
}

export function detectExitCondition(
  signal: Signal,
  recentPrices: PriceRow[],
  today: string,
): ExitEvent | null {
  if (recentPrices.length < 3) return null;

  const { strategy, entry_price: entryPrice, stop_loss: stopLoss, take_profit: takeProfit, signal_date, position_meta } = signal;
  const holdingDays = calcHoldingDays(signal_date, today);
  const storedRegime = signal.indicators?.market_regime;
  const maxHoldingDays = strategy === 'strategy_b'
    ? (storedRegime === 'bull' ? MAX_HOLDING_DAYS_B_BULL : MAX_HOLDING_DAYS_B)
    : MAX_HOLDING_DAYS_A;

  const closes = recentPrices.map((p) => p.close);
  const highs = recentPrices.map((p) => p.high ?? p.close);
  const lows = recentPrices.map((p) => p.low ?? p.close);
  const last = closes.length - 1;
  const current = recentPrices[last];
  const high = current.high ?? current.close;
  const low = current.low ?? current.close;
  const close = current.close;

  const ret = (price: number) => Math.round(((price - entryPrice) / entryPrice) * 10000) / 100;

  const maCrossConfirmDays = storedRegime === 'bull'
    ? MA_CROSS_CONFIRM_DAYS_BULL
    : storedRegime === 'bear'
      ? MA_CROSS_CONFIRM_DAYS_BEAR
      : STRATEGY_A_MA_CROSS_CONFIRM_DAYS;

  // ── Strategy A: 2-phase exit (50/50) + adaptive MA cross ────────────────
  if (strategy === 'strategy_a') {
    const sma5 = calcSMA(closes, 5);
    const sma25 = calcSMA(closes, 25);
    const maCrossDown = isMACrossDown(closes, sma5, sma25, maCrossConfirmDays);

    if (position_meta?.partial_exited) {
      const adjustedSl = position_meta.adjusted_sl;
      const hwm = Math.max(position_meta.high_water_mark, high);
      const atrLine = calcATR(highs, lows, closes, 14);
      const atr = atrLine[last];
      let activeSl = adjustedSl;
      if (atr !== null) {
        const trail = hwm - TRAIL_STOP_ATR_MULTIPLIER * atr;
        if (trail > activeSl) activeSl = trail;
      }

      const partialReturnPct = ret(position_meta.partial_exit_price);
      const blended = (finalPrice: number) =>
        Math.round((partialReturnPct * PARTIAL_EXIT_RATIO + ret(finalPrice) * (1 - PARTIAL_EXIT_RATIO)) * 100) / 100;

      if (low <= activeSl) {
        return { type: 'trailing_stop', exitPrice: activeSl, returnPct: ret(activeSl), blendedReturnPct: blended(activeSl), holdingDays };
      }
      if (maCrossDown) {
        return { type: 'ma_cross', exitPrice: close, returnPct: ret(close), blendedReturnPct: blended(close), holdingDays };
      }
      if (holdingDays >= maxHoldingDays) {
        return { type: 'time_expiry', exitPrice: close, returnPct: ret(close), blendedReturnPct: blended(close), holdingDays };
      }
      return null;
    }

    if (stopLoss !== null && low <= stopLoss) {
      return { type: 'stop_loss', exitPrice: stopLoss, returnPct: ret(stopLoss), holdingDays };
    }
    if (takeProfit !== null && high >= takeProfit) {
      const updatedMeta: PositionMeta = {
        partial_exited: true,
        adjusted_sl: entryPrice,
        high_water_mark: high,
        partial_exit_price: takeProfit,
        partial_exit_date: today,
      };
      return { type: 'partial_take_profit', exitPrice: takeProfit, returnPct: ret(takeProfit), holdingDays, updatedMeta };
    }
    if (maCrossDown) {
      return { type: 'ma_cross', exitPrice: close, returnPct: ret(close), holdingDays };
    }
    if (holdingDays >= maxHoldingDays) {
      return { type: 'time_expiry', exitPrice: close, returnPct: ret(close), holdingDays };
    }
    return null;
  }

  // ── Strategy C: partial exit + trailing stop ──────────────────────────────
  if (strategy === 'strategy_c') {
    if (position_meta?.partial_exited) {
      const adjustedSl = position_meta.adjusted_sl;
      const hwm = Math.max(position_meta.high_water_mark, high);
      const atrLine = calcATR(highs, lows, closes, 14);
      const atr = atrLine[last];
      let activeSl = adjustedSl;
      if (atr !== null) {
        const trail = hwm - STRATEGY_C_TRAIL_ATR_MULT * atr;
        if (trail > activeSl) activeSl = trail;
      }

      const partialReturnPct = ret(position_meta.partial_exit_price);
      const blended = (finalPrice: number) =>
        Math.round((partialReturnPct * STRATEGY_C_PARTIAL_EXIT_RATIO + ret(finalPrice) * (1 - STRATEGY_C_PARTIAL_EXIT_RATIO)) * 100) / 100;

      if (low <= activeSl) {
        return { type: 'trailing_stop', exitPrice: activeSl, returnPct: ret(activeSl), blendedReturnPct: blended(activeSl), holdingDays };
      }
      if (holdingDays >= MAX_HOLDING_DAYS_C) {
        return { type: 'time_expiry', exitPrice: close, returnPct: ret(close), blendedReturnPct: blended(close), holdingDays };
      }
      return null;
    }

    if (stopLoss !== null && low <= stopLoss) {
      return { type: 'stop_loss', exitPrice: stopLoss, returnPct: ret(stopLoss), holdingDays };
    }
    if (takeProfit !== null && high >= takeProfit) {
      const updatedMeta: PositionMeta = {
        partial_exited: true,
        adjusted_sl: entryPrice,
        high_water_mark: high,
        partial_exit_price: takeProfit,
        partial_exit_date: today,
      };
      return { type: 'partial_take_profit', exitPrice: takeProfit, returnPct: ret(takeProfit), holdingDays, updatedMeta };
    }
    if (holdingDays >= MAX_HOLDING_DAYS_C) {
      return { type: 'time_expiry', exitPrice: close, returnPct: ret(close), holdingDays };
    }
    return null;
  }

  // ── Strategy B (simple full exit) ─────────────────────────────────────────
  if (stopLoss !== null && low <= stopLoss) {
    return { type: 'stop_loss', exitPrice: stopLoss, returnPct: ret(stopLoss), holdingDays };
  }
  if (takeProfit !== null && high >= takeProfit) {
    return { type: 'take_profit', exitPrice: takeProfit, returnPct: ret(takeProfit), holdingDays };
  }
  if (holdingDays >= maxHoldingDays) {
    return { type: 'time_expiry', exitPrice: close, returnPct: ret(close), holdingDays };
  }
  return null;
}
