import { getSupabaseAdmin } from '../supabase';
import type { SignalOutcome, Signal } from '../types/database';

export type TradeRecord = SignalOutcome & {
  signal?: Pick<Signal, 'stock_code' | 'strategy' | 'grade' | 'entry_price'> | null;
};

export async function getClosedTrades(limit = 500): Promise<TradeRecord[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_signal_outcomes')
    .select('*, signal:us_signals(stock_code, strategy, grade, entry_price)')
    .order('exit_date', { ascending: false })
    .limit(limit);
  if (error) throw new Error(`getClosedTrades failed: ${error.message}`);
  return (data ?? []) as TradeRecord[];
}

export type TradeStats = {
  total: number;
  wins: number;
  losses: number;
  winRate: number;
  avgReturnPct: number;
  totalReturnPct: number;
};

export function computeTradeStats(trades: TradeRecord[]): TradeStats {
  const total = trades.length;
  if (total === 0) {
    return { total: 0, wins: 0, losses: 0, winRate: 0, avgReturnPct: 0, totalReturnPct: 0 };
  }
  const wins = trades.filter((t) => t.return_pct > 0).length;
  const losses = total - wins;
  const totalReturnPct = trades.reduce((s, t) => s + t.return_pct, 0);
  return {
    total,
    wins,
    losses,
    winRate: (wins / total) * 100,
    avgReturnPct: totalReturnPct / total,
    totalReturnPct,
  };
}

export type EquityPoint = { date: string; cumulative: number };

export function computeEquityCurve(trades: TradeRecord[]): EquityPoint[] {
  const asc = [...trades].sort(
    (a, b) => new Date(a.exit_date).getTime() - new Date(b.exit_date).getTime(),
  );
  let cum = 0;
  return asc.map((t) => {
    cum += t.return_pct;
    return { date: t.exit_date, cumulative: Number(cum.toFixed(2)) };
  });
}
