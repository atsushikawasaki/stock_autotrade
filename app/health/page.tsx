import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table';
import { HealthBadge } from '@/components/dashboard/health-badge';
import { Badge } from '@/components/ui/badge';
import { getHeartbeats, isHeartbeatHealthy } from '@/lib/queries/health';
import { getRecentSignals } from '@/lib/queries/signals';
import { formatDateTime } from '@/lib/utils';

export const dynamic = 'force-dynamic';

function ageLabel(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default async function HealthPage() {
  const [heartbeats, signals] = await Promise.all([
    getHeartbeats(),
    getRecentSignals(30),
  ]);
  const latest = heartbeats[0] ?? null;
  const healthy = isHeartbeatHealthy(latest);
  const signalsWithReason = signals.filter((s) => s.reason);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Health</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Executorのハートビートと直近のシグナル理由
          </p>
        </div>
        <HealthBadge hb={latest} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Executor Heartbeats</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {heartbeats.length === 0 ? (
            <div className="px-5 pb-5 text-sm text-zinc-500">ハートビートなし</div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>ID</TH>
                  <TH>Status</TH>
                  <TH>Last Heartbeat</TH>
                  <TH>Age</TH>
                </TR>
              </THead>
              <TBody>
                {heartbeats.map((hb) => (
                  <TR key={hb.id}>
                    <TD className="font-medium">{hb.id}</TD>
                    <TD>
                      <Badge variant={hb.status === 'running' && healthy ? 'success' : 'danger'}>
                        {hb.status}
                      </Badge>
                    </TD>
                    <TD>{formatDateTime(hb.last_heartbeat)}</TD>
                    <TD className="text-zinc-500">{ageLabel(hb.last_heartbeat)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>直近シグナル理由（30件）</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {signalsWithReason.length === 0 ? (
            <div className="px-5 pb-5 text-sm text-zinc-500">理由記録なし</div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Date</TH>
                  <TH>Code</TH>
                  <TH>Reason</TH>
                </TR>
              </THead>
              <TBody>
                {signalsWithReason.map((s) => (
                  <TR key={s.id}>
                    <TD className="text-zinc-500">{s.signal_date}</TD>
                    <TD className="font-medium">{s.stock_code}</TD>
                    <TD className="text-zinc-600 dark:text-zinc-400">{s.reason}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
