import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, THead, TBody, TR, TH } from '@/components/ui/table';
import { StockToggleRow } from '@/components/stocks/stock-toggle-row';
import { getAllStocks } from '@/lib/queries/stocks';

export const dynamic = 'force-dynamic';

export default async function StocksPage() {
  const stocks = await getAllStocks();
  const active = stocks.filter((s) => s.is_active).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Stocks</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          監視銘柄 — {active} / {stocks.length} active
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>銘柄一覧</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>Code</TH>
                <TH>Name</TH>
                <TH>Sector</TH>
                <TH>Active</TH>
              </TR>
            </THead>
            <TBody>
              {stocks.map((s) => (
                <StockToggleRow key={s.id} stock={s} />
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
