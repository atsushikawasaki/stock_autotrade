'use client';

import { useEffect, useState } from 'react';
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { formatCurrency, formatDate } from '@/lib/utils';
import type { Position } from '@/lib/types/database';

function daysBetween(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / (24 * 60 * 60 * 1000));
}

function pnlColor(value: number): string {
  if (value > 0) return 'text-emerald-600 dark:text-emerald-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return 'text-zinc-500';
}

interface PositionsTableProps {
  positions: Position[];
}

export function PositionsTable({ positions }: PositionsTableProps) {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (positions.length === 0) {
      setLoading(false);
      return;
    }
    const codes = [...new Set(positions.map((p) => p.stock_code))];
    fetch(`/api/positions/prices?codes=${codes.join(',')}`)
      .then((res) => res.json())
      .then((json) => {
        if (json.success) {
          setPrices(json.data);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [positions]);

  if (positions.length === 0) {
    return <div className="px-5 pb-5 text-sm text-zinc-500">保有なし</div>;
  }

  return (
    <Table>
      <THead>
        <TR>
          <TH>Opened</TH>
          <TH>Code</TH>
          <TH className="text-right">Qty</TH>
          <TH className="text-right">Entry</TH>
          <TH className="text-right">Current</TH>
          <TH className="text-right">PnL</TH>
          <TH className="text-right">PnL%</TH>
          <TH className="text-right">SL</TH>
          <TH className="text-right">TP</TH>
          <TH className="text-right">Days</TH>
          <TH>Status</TH>
        </TR>
      </THead>
      <TBody>
        {positions.map((p) => {
          const current = prices[p.stock_code];
          const hasCurrent = current != null && !loading;
          const pnl = hasCurrent ? (current - p.entry_price) * p.quantity : null;
          const pnlPct = hasCurrent ? ((current - p.entry_price) / p.entry_price) * 100 : null;

          return (
            <TR key={p.id}>
              <TD className="text-zinc-500">{formatDate(p.opened_at)}</TD>
              <TD className="font-medium">{p.stock_code}</TD>
              <TD className="text-right tabular-nums">{p.quantity}</TD>
              <TD className="text-right tabular-nums">{formatCurrency(p.entry_price)}</TD>
              <TD className="text-right tabular-nums">
                {loading ? (
                  <span className="text-zinc-400">...</span>
                ) : hasCurrent ? (
                  formatCurrency(current)
                ) : (
                  '—'
                )}
              </TD>
              <TD className={`text-right tabular-nums ${pnl != null ? pnlColor(pnl) : ''}`}>
                {pnl != null ? (
                  <>
                    {pnl >= 0 ? '+' : ''}
                    {formatCurrency(pnl)}
                  </>
                ) : (
                  '—'
                )}
              </TD>
              <TD className={`text-right tabular-nums ${pnlPct != null ? pnlColor(pnlPct) : ''}`}>
                {pnlPct != null ? (
                  <>
                    {pnlPct >= 0 ? '+' : ''}
                    {pnlPct.toFixed(2)}%
                  </>
                ) : (
                  '—'
                )}
              </TD>
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
          );
        })}
      </TBody>
    </Table>
  );
}
