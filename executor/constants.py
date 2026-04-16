"""Trading constants — mirrors TypeScript lib/constants.ts."""

# ─── Strategy A (N-Day High Breakout — buy momentum breakouts) ────────────────
STRATEGY_A_ADX_MIN = 20
STRATEGY_A_BREAKOUT_LOOKBACK = 20      # N-day high breakout period
STRATEGY_A_RSI_MIN = 50               # momentum (not oversold)
STRATEGY_A_RSI_MAX = 75               # not extremely overbought
STRATEGY_A_VOLUME_RATIO_MIN = 1.3     # volume surge on breakout
STRATEGY_A_SL_ATR_MULT = 2.0          # moderate SL
STRATEGY_A_TP_ATR_MULT = 4.0          # wide TP — let breakouts run

# ─── Strategy B (Deep Oversold Reversal — only in long-term uptrend) ─────────
STRATEGY_B_RSI_THRESHOLD = 35
STRATEGY_B_BB_PROXIMITY_PCT = 3
STRATEGY_B_VOLUME_RATIO_MIN = 1.2      # capitulation volume required
STRATEGY_B_CANDLE_BODY_PCT = 30        # bullish candle body >= 30% of range
STRATEGY_B_SMA_PERIOD = 100            # long-term trend filter (was 200, too strict)

# ─── Grade Filter (only execute signals at or above this grade) ──────────────
MIN_TRADE_GRADE = "B"  # Execute A and B grade signals

# ─── Strategy Enable Flags ───────────────────────────────────────────────────
STRATEGY_A_ENABLED = True
STRATEGY_B_ENABLED = False  # disabled: net negative at small position sizes
STRATEGY_C_ENABLED = True

# ─── Strategy C (SMA Golden Cross Momentum) ──────────────────────────────────
STRATEGY_C_ADX_MIN = 20
STRATEGY_C_GC_LOOKBACK = 1
STRATEGY_C_RSI_MIN = 50
STRATEGY_C_RSI_MAX = 65
STRATEGY_C_SL_ATR_MULT = 2.5
STRATEGY_C_TP_ATR_MULT = 3.0

# ─── Risk Management ──────────────────────────────────────────────────────────
SL_ATR_MULTIPLIER = 2.5
TP_ATR_MULTIPLIER = 3.5
MAX_HOLDING_DAYS_A = 20
MAX_HOLDING_DAYS_B = 15
MAX_HOLDING_DAYS_B_BULL = 20
STRATEGY_B_SL_ATR_MULT = 2.0          # moderate SL for reversal trades
STRATEGY_B_TP_ATR_MULT = 3.0          # wide TP — let winners run
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

# ─── Claude AI ────────────────────────────────────────────────────────────────
CLAUDE_ENABLED = True              # Entry validation gate
CLAUDE_EXIT_ENABLED = True         # Exit advisor
CLAUDE_REVIEW_ENABLED = True       # Daily trade review
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MIN_CONFIDENCE = 60         # Minimum confidence to approve entry
CLAUDE_TIMEOUT_SECONDS = 15
CLAUDE_EARNINGS_BLACKOUT_DAYS = 5  # Caution zone around earnings

# ─── Notification ─────────────────────────────────────────────────────────────
NOTIFY_GRADES = ("A", "B")  # Aligned with MIN_TRADE_GRADE
