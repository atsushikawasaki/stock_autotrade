import { getSupabaseAdmin } from '../supabase';
import type { BacktestResult } from '../types/database';

export async function getBacktestResults(): Promise<BacktestResult[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_backtest_results')
    .select('*')
    .order('total_pnl', { ascending: false });
  if (error) throw new Error(`getBacktestResults failed: ${error.message}`);
  return (data ?? []) as BacktestResult[];
}
