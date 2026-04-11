import { getSupabaseAdmin } from '../supabase';
import type { ExecutorHeartbeat } from '../types/database';

export async function getHeartbeats(): Promise<ExecutorHeartbeat[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from('us_executor_heartbeat')
    .select('*')
    .order('last_heartbeat', { ascending: false });
  if (error) throw new Error(`getHeartbeats failed: ${error.message}`);
  return (data ?? []) as ExecutorHeartbeat[];
}

export async function getLatestHeartbeat(): Promise<ExecutorHeartbeat | null> {
  const all = await getHeartbeats();
  return all[0] ?? null;
}

/** Executor is considered healthy if last heartbeat is within 10 minutes. */
export function isHeartbeatHealthy(hb: ExecutorHeartbeat | null, maxAgeMs = 10 * 60 * 1000): boolean {
  if (!hb) return false;
  const age = Date.now() - new Date(hb.last_heartbeat).getTime();
  return age <= maxAgeMs && hb.status === 'running';
}
