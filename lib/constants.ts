// ─── Strategy A (RSI Momentum + MACD + Trend) ────────────────────────────────
export const STRATEGY_A_RSI_CROSS_LEVEL = 50;
export const STRATEGY_A_ADX_MIN = 20;
export const STRATEGY_A_ADX_MAX = 27;
export const STRATEGY_A_RSI_CROSS_LOOKBACK = 2;
export const STRATEGY_A_RSI_MIN_AT_SIGNAL = 53;
export const STRATEGY_A_MACD_HIST_MAX_RATIO = 0.03;
export const STRATEGY_A_VOLUME_RATIO_MIN = 1.2;

// ─── Strategy C (SMA Golden Cross Momentum) ──────────────────────────────────
export const STRATEGY_C_GC_LOOKBACK = 1;
export const STRATEGY_C_RSI_MAX = 65;
export const STRATEGY_C_RSI_MIN = 50;
export const STRATEGY_C_SL_ATR_MULT = 2.5;
export const STRATEGY_C_TP_ATR_MULT = 3.0;
export const MAX_HOLDING_DAYS_C = 30;

// ─── Strategy B (BB Lower Touch + Deep Oversold) ─────────────────────────────
export const STRATEGY_B_RSI_THRESHOLD = 40;
export const STRATEGY_B_BB_PROXIMITY_PCT = 3;
export const STRATEGY_B_BB_BANDWIDTH_MAX = 0.15;

// ─── Risk Management ──────────────────────────────────────────────────────────
export const SL_ATR_MULTIPLIER = 2;
export const TP_ATR_MULTIPLIER = 3;
export const MAX_HOLDING_DAYS_A = 30;
export const MAX_HOLDING_DAYS_B = 10;
export const MAX_HOLDING_DAYS_B_BULL = 15;

// ─── Strategy A: Partial exit + trailing stop ─────────────────────────────────
export const PARTIAL_EXIT_RATIO = 0.5;
export const TRAIL_STOP_ATR_MULTIPLIER = 1.5;
export const STRATEGY_A_MA_CROSS_CONFIRM_DAYS = 2;

// ─── Signal Scoring (per-strategy thresholds) ────────────────────────────────
export const SCORE_A_GRADE_A_MIN = 75;
export const SCORE_A_GRADE_B_MIN = 65;
export const SCORE_A_GRADE_C_MIN = 55;

export const SCORE_B_GRADE_A_MIN = 75;
export const SCORE_B_GRADE_B_MIN = 65;
export const SCORE_B_GRADE_C_MIN = 55;

export const SCORE_C_GRADE_A_MIN = 70;
export const SCORE_C_GRADE_B_MIN = 60;
export const SCORE_C_GRADE_C_MIN = 50;

// ─── Regime-linked SL/TP Multipliers ─────────────────────────────────────────
export const TP_ATR_MULTIPLIER_BULL = 3.5;
export const SL_ATR_MULTIPLIER_BEAR = 1.5;

// ─── Adaptive MA Cross Exit ──────────────────────────────────────────────────
export const MA_CROSS_CONFIRM_DAYS_BULL = 3;
export const MA_CROSS_CONFIRM_DAYS_BEAR = 1;

// ─── Strategy C: Partial Exit + Trailing ─────────────────────────────────────
export const STRATEGY_C_PARTIAL_EXIT_RATIO = 0.5;
export const STRATEGY_C_TRAIL_ATR_MULT = 2.0;

// ─── Volume / Ichimoku Penalties ─────────────────────────────────────────────
export const STRATEGY_B_LOW_VOL_THRESHOLD = 0.8;
export const STRATEGY_B_LOW_VOL_PENALTY = -8;
export const STRATEGY_C_BELOW_KUMO_PENALTY = -10;

// ─── Market Filter (US market: S&P 500 via SPY ETF) ─────────────────────────
export const MARKET_INDEX_SYMBOL = 'SPY';
export const MARKET_SMA_FAST = 50;
export const MARKET_SMA_SLOW = 200;

// ─── Cache ────────────────────────────────────────────────────────────────────
export const HISTORY_DAYS_ANALYSIS = 120;
export const HISTORY_DAYS_BACKTEST = 730;

// ─── Cron ─────────────────────────────────────────────────────────────────────
export const NOTIFY_GRADES: readonly string[] = ['A', 'B', 'C'];
export const MIN_NOTIFY_INTERVAL_HOURS = 2;

// ─── NYSE Trading Hours (in UTC) ─────────────────────────────────────────────
/** NYSE opens at 14:30 UTC (9:30 AM ET) */
export const NYSE_OPEN_UTC_HOUR = 14;
export const NYSE_OPEN_UTC_MINUTE = 30;
/** NYSE closes at 21:00 UTC (4:00 PM ET) */
export const NYSE_CLOSE_UTC_HOUR = 21;
export const NYSE_CLOSE_UTC_MINUTE = 0;

// ─── moomoo Symbol Prefix ────────────────────────────────────────────────────
export const MOOMOO_SYMBOL_PREFIX = 'US.';
