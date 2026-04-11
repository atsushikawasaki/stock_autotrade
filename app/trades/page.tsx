import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { EquityCurve } from '@/components/trades/equity-curve';
import { StrategyLabel } from '@/components/signals/strategy-label';
import {
  getClosedTrades,
  computeTradeStats,
  computeEquityCurve,
} from '@/lib/queries/trades';
import { formatDate, formatPct } from '@/lib/utils';

export const dynamic = 'force-dynamic';

export default async function TradesPage() {
  const trades = await getClosedTrades(500);
  const stats = computeTradeStats(trades);
  const curve = computeEquityCurve(trades);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Trades</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">クローズ済みトレード履歴</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total trades"
          value={String(stats.total)}
          subtitle={`${stats.wins}W / ${stats.losses}L`}
        />
        <KpiCard
          title="勝率"
          value={`${stats.winRate.toFixed(1)}%`}
        />
        <KpiCard
          title="平均リターン"
          value={formatPct(stats.avgReturnPct)}
          tone={stats.avgReturnPct > 0 ? 'positive' : stats.avgReturnPct < 0 ? 'negative' : 'default'}
        />
        <KpiCard
          title="累積リターン"
          value={formatPct(stats.totalReturnPct)}
          tone={stats.totalReturnPct > 0 ? 'positive' : stats.totalReturnPct < 0 ? 'negative' : 'default'}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>エクイティカーブ（累積 P&L %）</CardTitle>
        </CardHeader>
        <CardContent>
          <EquityCurve data={curve} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>取引履歴</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {trades.length === 0 ? (
            <div className="px-5 pb-5 text-sm text-zinc-500">履歴なし</div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Exit Date</TH>
                  <TH>Code</TH>
                  <TH>Strategy</TH>
                  <TH>Exit Reason</TH>
                  <TH className="text-right">Holding</TH>
                  <TH className="text-right">Return</TH>
                </TR>
              </THead>
              <TBody>
                {trades.map((t) => (
                  <TR key={t.id}>
                    <TD className="text-zinc-500">{formatDate(t.exit_date)}</TD>
                    <TD className="font-medium">{t.signal?.stock_code ?? '—'}</TD>
                    <TD>
                      {t.signal?.strategy ? <StrategyLabel strategy={t.signal.strategy} /> : '—'}
                    </TD>
                    <TD><Badge variant="neutral">{t.exit_reason}</Badge></TD>
                    <TD className="text-right tabular-nums">{t.holding_days}d</TD>
                    <TD
                      className={
                        'text-right tabular-nums font-medium ' +
                        (t.return_pct > 0
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : t.return_pct < 0
                          ? 'text-red-600 dark:text-red-400'
                          : '')
                      }
                    >
                      {formatPct(t.return_pct)}
                    </TD>
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
