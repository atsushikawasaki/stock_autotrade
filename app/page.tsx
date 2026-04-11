import { DollarSign, Target, Briefcase, Activity } from 'lucide-react';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { HealthBadge } from '@/components/dashboard/health-badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table';
import { GradeBadge } from '@/components/signals/grade-badge';
import { StrategyLabel } from '@/components/signals/strategy-label';
import { StatusBadge } from '@/components/signals/status-badge';
import { getRecentSignals } from '@/lib/queries/signals';
import { getOpenPositions } from '@/lib/queries/positions';
import { getClosedTrades, computeTradeStats } from '@/lib/queries/trades';
import { getLatestHeartbeat } from '@/lib/queries/health';
import { formatCurrency, formatDate, formatPct } from '@/lib/utils';

export const dynamic = 'force-dynamic';

export default async function OverviewPage() {
  const [signals, positions, trades, hb] = await Promise.all([
    getRecentSignals(5),
    getOpenPositions(),
    getClosedTrades(500),
    getLatestHeartbeat(),
  ]);

  const stats = computeTradeStats(trades);
  const pnlTone = stats.totalReturnPct > 0 ? 'positive' : stats.totalReturnPct < 0 ? 'negative' : 'default';

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            自動売買の現在状況とパフォーマンス
          </p>
        </div>
        <HealthBadge hb={hb} />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="累積 P&L"
          value={formatPct(stats.totalReturnPct)}
          subtitle={`${stats.total} trades closed`}
          icon={DollarSign}
          tone={pnlTone}
        />
        <KpiCard
          title="勝率"
          value={`${stats.winRate.toFixed(1)}%`}
          subtitle={`${stats.wins}W / ${stats.losses}L`}
          icon={Target}
        />
        <KpiCard
          title="オープンポジション"
          value={String(positions.length)}
          subtitle="現在保有中"
          icon={Briefcase}
        />
        <KpiCard
          title="平均リターン"
          value={formatPct(stats.avgReturnPct)}
          subtitle="per trade"
          icon={Activity}
          tone={stats.avgReturnPct > 0 ? 'positive' : stats.avgReturnPct < 0 ? 'negative' : 'default'}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>最新シグナル</CardTitle>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            {signals.length === 0 ? (
              <div className="px-5 pb-5 text-sm text-zinc-500">シグナルなし</div>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>Date</TH>
                    <TH>Code</TH>
                    <TH>Strategy</TH>
                    <TH>Grade</TH>
                    <TH>Status</TH>
                  </TR>
                </THead>
                <TBody>
                  {signals.map((s) => (
                    <TR key={s.id}>
                      <TD className="text-zinc-500">{formatDate(s.signal_date)}</TD>
                      <TD className="font-medium">{s.stock_code}</TD>
                      <TD><StrategyLabel strategy={s.strategy} /></TD>
                      <TD><GradeBadge grade={s.grade} /></TD>
                      <TD><StatusBadge status={s.status} /></TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>オープンポジション</CardTitle>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            {positions.length === 0 ? (
              <div className="px-5 pb-5 text-sm text-zinc-500">保有なし</div>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>Opened</TH>
                    <TH>Code</TH>
                    <TH className="text-right">Entry</TH>
                    <TH className="text-right">SL</TH>
                    <TH className="text-right">TP</TH>
                  </TR>
                </THead>
                <TBody>
                  {positions.map((p) => (
                    <TR key={p.id}>
                      <TD className="text-zinc-500">{formatDate(p.opened_at)}</TD>
                      <TD className="font-medium">{p.stock_code}</TD>
                      <TD className="text-right">{formatCurrency(p.entry_price)}</TD>
                      <TD className="text-right">
                        {p.stop_loss != null ? formatCurrency(p.stop_loss) : '—'}
                      </TD>
                      <TD className="text-right">
                        {p.take_profit != null ? formatCurrency(p.take_profit) : '—'}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
