import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { getAllPositions } from '@/lib/queries/positions';
import { formatCurrency, formatDate } from '@/lib/utils';

export const dynamic = 'force-dynamic';

function daysBetween(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / (24 * 60 * 60 * 1000));
}

export default async function PositionsPage() {
  const positions = await getAllPositions(200);
  const open = positions.filter((p) => p.status === 'open' || p.status === 'partial_closed');
  const closed = positions.filter((p) => p.status === 'closed');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Positions</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          オープン中 {open.length} / クローズ済 {closed.length}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>オープンポジション</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {open.length === 0 ? (
            <div className="px-5 pb-5 text-sm text-zinc-500">保有なし</div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Opened</TH>
                  <TH>Code</TH>
                  <TH className="text-right">Qty</TH>
                  <TH className="text-right">Entry</TH>
                  <TH className="text-right">SL</TH>
                  <TH className="text-right">TP</TH>
                  <TH className="text-right">Days</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {open.map((p) => (
                  <TR key={p.id}>
                    <TD className="text-zinc-500">{formatDate(p.opened_at)}</TD>
                    <TD className="font-medium">{p.stock_code}</TD>
                    <TD className="text-right tabular-nums">{p.quantity}</TD>
                    <TD className="text-right tabular-nums">{formatCurrency(p.entry_price)}</TD>
                    <TD className="text-right tabular-nums">
                      {p.stop_loss != null ? formatCurrency(p.stop_loss) : '—'}
                    </TD>
                    <TD className="text-right tabular-nums">
                      {p.take_profit != null ? formatCurrency(p.take_profit) : '—'}
                    </TD>
                    <TD className="text-right tabular-nums">{daysBetween(p.opened_at)}</TD>
                    <TD>
                      <Badge variant={p.status === 'partial_closed' ? 'warning' : 'info'}>
                        {p.status}
                      </Badge>
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
