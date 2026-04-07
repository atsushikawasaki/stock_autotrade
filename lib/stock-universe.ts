import { supabaseAdmin } from '@/lib/supabase';
import type { Stock } from '@/lib/types/database';

/** Fetch all active US stocks from Supabase */
export async function getActiveStocks(): Promise<Stock[]> {
  const { data, error } = await supabaseAdmin
    .from('us_stocks')
    .select('*')
    .eq('is_active', true)
    .order('code');

  if (error) {
    console.error('Failed to fetch active stocks:', error);
    return [];
  }

  return data as Stock[];
}
