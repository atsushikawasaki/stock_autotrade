import { getSupabaseAdmin } from '../supabase';
import type { BacktestResult } from '../types/database';

export async function getBacktestResults(): Promise<BacktestResult[]> {
  try {
    const sb = getSupabaseAdmin();
    const { data, error } = await sb
      .from('us_backtest_results')
      .select('*')
      .order('total_pnl', { ascending: false });
    if (error) {
      console.error('getBacktestResults query error:', error);
      return [];
    }
    return (data ?? []) as BacktestResult[];
  } catch (e) {
    console.error('getBacktestResults exception:', e);
    return [];
  }
}
