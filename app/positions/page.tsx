import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getAllPositions } from '@/lib/queries/positions';
import { PositionsTable } from './positions-table';

export const dynamic = 'force-dynamic';

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
          <PositionsTable positions={open} />
        </CardContent>
      </Card>
    </div>
  );
}
