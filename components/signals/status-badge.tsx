import { Badge } from '@/components/ui/badge';
import type { SignalStatus } from '@/lib/types/database';

const map: Record<SignalStatus, { variant: 'success' | 'info' | 'neutral' | 'danger'; label: string }> = {
  pending: { variant: 'info', label: 'pending' },
  executed: { variant: 'success', label: 'executed' },
  cancelled: { variant: 'neutral', label: 'cancelled' },
  expired: { variant: 'danger', label: 'expired' },
};

export function StatusBadge({ status }: { status: SignalStatus }) {
  const m = map[status] ?? { variant: 'neutral' as const, label: status };
  return <Badge variant={m.variant}>{m.label}</Badge>;
}
