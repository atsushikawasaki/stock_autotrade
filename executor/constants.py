"""Trading constants — mirrors TypeScript lib/constants.ts."""

# ─── Strategy A (RSI Momentum + MACD + Trend) ────────────────────────────────
STRATEGY_A_RSI_CROSS_LEVEL = 50
STRATEGY_A_ADX_MIN = 20
STRATEGY_A_ADX_MAX = 27
STRATEGY_A_RSI_CROSS_LOOKBACK = 2
STRATEGY_A_RSI_MIN_AT_SIGNAL = 53
STRATEGY_A_MACD_HIST_MAX_RATIO = 0.03
STRATEGY_A_VOLUME_RATIO_MIN = 1.2

# ─── Strategy B (BB Lower Touch + Deep Oversold) ─────────────────────────────
STRATEGY_B_RSI_THRESHOLD = 40
STRATEGY_B_BB_PROXIMITY_PCT = 3
STRATEGY_B_BB_BANDWIDTH_MAX = 0.15

# ─── Strategy C (SMA Golden Cross Momentum) ──────────────────────────────────
STRATEGY_C_GC_LOOKBACK = 1
STRATEGY_C_RSI_MIN = 50
STRATEGY_C_RSI_MAX = 65
STRATEGY_C_SL_ATR_MULT = 2.5
STRATEGY_C_TP_ATR_MULT = 3.0

# ─── Risk Management ──────────────────────────────────────────────────────────
SL_ATR_MULTIPLIER = 2
TP_ATR_MULTIPLIER = 3
MAX_HOLDING_DAYS_A = 30
MAX_HOLDING_DAYS_B = 10
MAX_HOLDING_DAYS_B_BULL = 15
MAX_HOLDING_DAYS_C = 30

TP_ATR_MULTIPLIER_BULL = 3.5
SL_ATR_MULTIPLIER_BEAR = 1.5

# ─── Signal Scoring Thresholds ───────────────────────────────────────────────
SCORE_A_GRADE_A_MIN = 75
SCORE_A_GRADE_B_MIN = 65
SCORE_A_GRADE_C_MIN = 55

SCORE_B_GRADE_A_MIN = 75
SCORE_B_GRADE_B_MIN = 65
SCORE_B_GRADE_C_MIN = 55

SCORE_C_GRADE_A_MIN = 70
SCORE_C_GRADE_B_MIN = 60
SCORE_C_GRADE_C_MIN = 50

# ─── Volume / Ichimoku Penalties ─────────────────────────────────────────────
STRATEGY_B_LOW_VOL_THRESHOLD = 0.8
STRATEGY_B_LOW_VOL_PENALTY = -8
STRATEGY_C_BELOW_KUMO_PENALTY = -10

# ─── Market Filter ────────────────────────────────────────────────────────────
MARKET_INDEX_SYMBOL = "SPY"
MARKET_SMA_FAST = 50
MARKET_SMA_SLOW = 200

# ─── Notification ─────────────────────────────────────────────────────────────
NOTIFY_GRADES = ("A", "B", "C")
