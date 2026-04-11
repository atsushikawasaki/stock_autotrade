import { getSupabaseAdmin } from '../supabase';
import type { Position } from '../types/database';

export async function getOpenPositions(): Promise<Position[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_positions')
    .select('*')
    .in('status', ['open', 'partial_closed'])
    .order('opened_at', { ascending: false });
  if (error) throw new Error(`getOpenPositions failed: ${error.message}`);
  return (data ?? []) as Position[];
}

export async function getAllPositions(limit = 200): Promise<Position[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_positions')
    .select('*')
    .order('opened_at', { ascending: false })
    .limit(limit);
  if (error) throw new Error(`getAllPositions failed: ${error.message}`);
  return (data ?? []) as Position[];
}
