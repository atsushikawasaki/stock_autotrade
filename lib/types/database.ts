export type Stock = {
  id: string;
  code: string;          // 'AAPL', 'MSFT' etc.
  name: string | null;
  sector: string | null;
  is_active: boolean;
  created_at: string;
};

export type DailyPrice = {
  id: string;
  stock_code: string;
  trade_date: string; // YYYY-MM-DD
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number;
  fetched_at: string;
};

export type SignalGrade = 'A' | 'B' | 'C' | 'D';
export type SignalStrategy = 'strategy_a' | 'strategy_b' | 'strategy_c';
export type SignalStatus = 'pending' | 'executed' | 'cancelled' | 'expired';
export type ExitReason =
  | 'take_profit'
  | 'partial_take_profit'
  | 'stop_loss'
  | 'trailing_stop'
  | 'ma_cross'
  | 'time_expiry'
  | 'claude_exit'
  | 'manual';

export type PositionStatus = 'open' | 'partial_closed' | 'closed';

export type PositionMeta = {
  partial_exited: boolean;
  adjusted_sl: number;
  high_water_mark: number;
  partial_exit_price: number;
  partial_exit_date: string;
  phase?: 1 | 2 | 3;
  realized_weighted_return?: number;
};

export type SignalIndicatorSnapshot = {
  rsi: number | null;
  sma5: number | null;
  sma25: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  bb_upper: number | null;
  bb_middle: number | null;
  bb_lower: number | null;
  atr: number | null;
  adx: number | null;
  stoch_k: number | null;
  stoch_d: number | null;
  volume: number;
  volume_sma20: number | null;
  volume_ratio: number | null;
  market_regime: 'bull' | 'bear' | 'neutral';
};

export type Signal = {
  id: string;
  stock_code: string;
  signal_date: string;
  strategy: SignalStrategy;
  direction: 'buy';
  score: number;
  grade: SignalGrade;
  entry_price: number;
  stop_loss: number | null;
  take_profit: number | null;
  indicators: SignalIndicatorSnapshot;
  reason: string | null;
  status: SignalStatus;
  executed_price: number | null;
  executed_qty: number | null;
  executed_at: string | null;
  moomoo_order_id: string | null;
  notified: boolean;
  position_meta: PositionMeta | null;
  created_at: string;
};

export type Position = {
  id: string;
  signal_id: string;
  stock_code: string;
  entry_price: number;
  quantity: number;
  stop_loss: number | null;
  take_profit: number | null;
  status: PositionStatus;
  position_meta: PositionMeta | null;
  moomoo_order_ids: string[];
  opened_at: string;
  closed_at: string | null;
};

export type SignalOutcome = {
  id: string;
  signal_id: string;
  position_id: string | null;
  exit_date: string;
  exit_price: number;
  exit_reason: ExitReason;
  return_pct: number;
  holding_days: number;
  notes: string | null;
  created_at: string;
};

export type BacktestResult = {
  id: string;
  stock_code: string;
  strategy: SignalStrategy;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_return_pct: number;
  total_pnl: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  avg_holding_days: number;
  backtest_date: string;
};

export type ExecutorHeartbeat = {
  id: string;
  last_heartbeat: string;
  status: 'running' | 'stopped' | 'error' | string;
};

export type DailyReview = {
  id: string;
  review_date: string;
  review_text: string;
  signals_count: number | null;
  exits_count: number | null;
  created_at: string;
};
