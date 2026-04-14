import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table';
import { StrategyLabel } from '@/components/signals/strategy-label';
import { BacktestRunner } from '@/components/strategy/backtest-runner';
import { getBacktestResults } from '@/lib/queries/backtest';
import { formatPct } from '@/lib/utils';
import type { BacktestResult, SignalStrategy } from '@/lib/types/database';

export const dynamic = 'force-dynamic';

type Aggregate = {
  strategy: SignalStrategy;
  trades: number;
  wins: number;
  winRate: number;
  avgReturn: number;
  totalPnl: number;
  sharpe: number;
  maxDD: number;
};

function aggregate(results: BacktestResult[]): Aggregate[] {
  const groups = new Map<SignalStrategy, BacktestResult[]>();
  for (const r of results) {
    const arr = groups.get(r.strategy) ?? [];
    arr.push(r);
    groups.set(r.strategy, arr);
  }
  return Array.from(groups.entries()).map(([strategy, rows]) => {
    const trades = rows.reduce((s, r) => s + r.total_trades, 0);
    const wins = rows.reduce((s, r) => s + r.wins, 0);
    const totalPnl = rows.reduce((s, r) => s + r.total_pnl, 0);
    const weightedReturn =
      trades === 0 ? 0 : rows.reduce((s, r) => s + r.avg_return_pct * r.total_trades, 0) / trades;
    const sharpe = rows.length === 0 ? 0 : rows.reduce((s, r) => s + r.sharpe_ratio, 0) / rows.length;
    const maxDD = rows.reduce((m, r) => Math.min(m, r.max_drawdown_pct), 0);
    return {
      strategy,
      trades,
      wins,
      winRate: trades === 0 ? 0 : (wins / trades) * 100,
      avgReturn: weightedReturn,
      totalPnl,
      sharpe,
      maxDD,
    };
  });
}

export default async function StrategyPage() {
  const results = await getBacktestResults();
  const aggregates = aggregate(results);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Strategy Performance</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          バックテスト結果（<code>us_backtest_results</code>）
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Run Backtest</CardTitle>
        </CardHeader>
        <CardContent>
          <BacktestRunner />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {aggregates.map((a) => (
          <Card key={a.strategy}>
            <CardHeader>
              <CardTitle><StrategyLabel strategy={a.strategy} /></CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-zinc-500">Trades</span>
                <span className="font-medium tabular-nums">{a.trades}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-zinc-500">Win rate</span>
                <span className="font-medium tabular-nums">{a.winRate.toFixed(1)}%</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-zinc-500">Avg return</span>
                <span
                  className={
                    'font-medium tabular-nums ' +
                    (a.avgReturn > 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-red-600 dark:text-red-400')
                  }
                >
                  {formatPct(a.avgReturn)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-zinc-500">Sharpe</span>
                <span className="font-medium tabular-nums">{a.sharpe.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-zinc-500">Max DD</span>
                <span className="font-medium tabular-nums text-red-600 dark:text-red-400">
                  {a.maxDD.toFixed(1)}%
                </span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>銘柄別バックテスト</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {results.length === 0 ? (
            <div className="px-5 pb-5 text-sm text-zinc-500">結果なし</div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Code</TH>
                  <TH>Strategy</TH>
                  <TH className="text-right">Trades</TH>
                  <TH className="text-right">Win %</TH>
                  <TH className="text-right">Avg Return</TH>
                  <TH className="text-right">Total P&L</TH>
                  <TH className="text-right">Sharpe</TH>
                  <TH className="text-right">Max DD</TH>
                </TR>
              </THead>
              <TBody>
                {results.map((r) => (
                  <TR key={r.id}>
                    <TD className="font-medium">{r.stock_code}</TD>
                    <TD><StrategyLabel strategy={r.strategy} /></TD>
                    <TD className="text-right tabular-nums">{r.total_trades}</TD>
                    <TD className="text-right tabular-nums">{r.win_rate.toFixed(1)}%</TD>
                    <TD
                      className={
                        'text-right tabular-nums ' +
                        (r.avg_return_pct > 0
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-red-600 dark:text-red-400')
                      }
                    >
                      {formatPct(r.avg_return_pct)}
                    </TD>
                    <TD className="text-right tabular-nums">{r.total_pnl.toFixed(2)}</TD>
                    <TD className="text-right tabular-nums">{r.sharpe_ratio.toFixed(2)}</TD>
                    <TD className="text-right tabular-nums text-red-600 dark:text-red-400">
                      {r.max_drawdown_pct.toFixed(1)}%
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
