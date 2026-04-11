import { getSupabaseAdmin } from '../supabase';
import type { Stock } from '../types/database';

export async function getAllStocks(): Promise<Stock[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_stocks')
    .select('*')
    .order('code', { ascending: true });
  if (error) throw new Error(`getAllStocks failed: ${error.message}`);
  return (data ?? []) as Stock[];
}

export async function setStockActive(code: string, isActive: boolean): Promise<void> {
  const sb = getSupabaseAdmin();
  const { error } = await sb
    .from('us_stocks')
    .update({ is_active: isActive })
    .eq('code', code);
  if (error) throw new Error(`setStockActive failed: ${error.message}`);
}
