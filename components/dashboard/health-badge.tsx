import { Badge } from '@/components/ui/badge';
import type { ExecutorHeartbeat } from '@/lib/types/database';
import { isHeartbeatHealthy } from '@/lib/queries/health';
import { formatDateTime } from '@/lib/utils';

export function HealthBadge({ hb }: { hb: ExecutorHeartbeat | null }) {
  const healthy = isHeartbeatHealthy(hb);
  if (!hb) {
    return <Badge variant="danger">No heartbeat</Badge>;
  }
  return (
    <div className="flex items-center gap-2">
      <Badge variant={healthy ? 'success' : 'danger'}>
        {healthy ? 'Running' : 'Stale'}
      </Badge>
      <span className="text-xs text-zinc-500 dark:text-zinc-400">
        {formatDateTime(hb.last_heartbeat)}
      </span>
    </div>
  );
}
