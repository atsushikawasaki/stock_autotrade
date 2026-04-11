import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table';
import { GradeBadge } from '@/components/signals/grade-badge';
import { StrategyLabel } from '@/components/signals/strategy-label';
import { StatusBadge } from '@/components/signals/status-badge';
import { getAllSignals } from '@/lib/queries/signals';
import { formatCurrency, formatDate } from '@/lib/utils';

export const dynamic = 'force-dynamic';

export default async function SignalsPage() {
  const signals = await getAllSignals(300);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Signals</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Executorが検出した全シグナル（最新300件）
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{signals.length} signals</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>Date</TH>
                <TH>Code</TH>
                <TH>Strategy</TH>
                <TH>Grade</TH>
                <TH className="text-right">Score</TH>
                <TH className="text-right">Entry</TH>
                <TH className="text-right">SL</TH>
                <TH className="text-right">TP</TH>
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
                  <TD className="text-right tabular-nums">{s.score}</TD>
                  <TD className="text-right tabular-nums">{formatCurrency(s.entry_price)}</TD>
                  <TD className="text-right tabular-nums">
                    {s.stop_loss != null ? formatCurrency(s.stop_loss) : '—'}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {s.take_profit != null ? formatCurrency(s.take_profit) : '—'}
                  </TD>
                  <TD><StatusBadge status={s.status} /></TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
