import { getSupabaseAdmin } from '../supabase';
import type { Signal, SignalStatus } from '../types/database';

export async function getRecentSignals(limit = 20): Promise<Signal[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_signals')
    .select('*')
    .order('signal_date', { ascending: false })
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) throw new Error(`getRecentSignals failed: ${error.message}`);
  return (data ?? []) as Signal[];
}

export async function getAllSignals(limit = 500): Promise<Signal[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_signals')
    .select('*')
    .order('signal_date', { ascending: false })
    .limit(limit);
  if (error) throw new Error(`getAllSignals failed: ${error.message}`);
  return (data ?? []) as Signal[];
}

export async function getSignalsByStatus(
  status: SignalStatus,
  limit = 100,
): Promise<Signal[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_signals')
    .select('*')
    .eq('status', status)
    .order('signal_date', { ascending: false })
    .limit(limit);
  if (error) throw new Error(`getSignalsByStatus failed: ${error.message}`);
  return (data ?? []) as Signal[];
}
