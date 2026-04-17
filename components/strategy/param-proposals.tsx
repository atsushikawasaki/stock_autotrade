'use client';

import { useEffect, useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface Proposal {
  id: string;
  strategy: string;
  current_params: Record<string, number>;
  proposed_params: Record<string, number>;
  optimization_method: string;
  metrics: {
    total_trades?: number;
    win_rate?: number;
    avg_return?: number;
    sharpe?: number;
    robustness?: number;
  };
  status: 'pending' | 'approved' | 'rejected' | 'applied';
  created_at: string;
}

const statusVariant: Record<string, 'info' | 'success' | 'danger' | 'warning'> = {
  pending: 'warning',
  approved: 'info',
  applied: 'success',
  rejected: 'danger',
};

export function ParamProposals() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const fetchProposals = useCallback(() => {
    fetch('/api/params/proposals')
      .then((res) => res.json())
      .then((json) => {
        if (json.success) setProposals(json.data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchProposals();
  }, [fetchProposals]);

  async function handleAction(id: string, action: 'approve' | 'reject') {
    setActing(id);
    try {
      const res = await fetch('/api/params/proposals', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, action }),
      });
      const json = await res.json();
      if (json.success) {
        fetchProposals();
      }
    } finally {
      setActing(null);
    }
  }

  if (loading) {
    return (
      <Card>
        <CardHeader><CardTitle>Parameter Proposals</CardTitle></CardHeader>
        <CardContent><p className="text-sm text-zinc-500">Loading...</p></CardContent>
      </Card>
    );
  }

  if (proposals.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Parameter Proposals</CardTitle></CardHeader>
        <CardContent><p className="text-sm text-zinc-500">提案なし</p></CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle>Parameter Proposals</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {proposals.map((p) => {
          const changes = Object.keys(p.proposed_params).filter(
            (k) => p.current_params[k] !== p.proposed_params[k],
          );

          return (
            <div
              key={p.id}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">
                    {p.strategy.replace('strategy_', '').toUpperCase()}
                  </span>
                  <Badge variant={statusVariant[p.status] ?? 'info'}>{p.status}</Badge>
                  <span className="text-xs text-zinc-400">{p.optimization_method}</span>
                </div>
                <span className="text-xs text-zinc-400">
                  {new Date(p.created_at).toLocaleDateString('ja-JP')}
                </span>
              </div>

              {/* Parameter changes */}
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
                {changes.map((key) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-zinc-500">{key}</span>
                    <span className="tabular-nums">
                      <span className="text-zinc-400">{p.current_params[key]}</span>
                      <span className="mx-1">→</span>
                      <span className="font-medium">{p.proposed_params[key]}</span>
                    </span>
                  </div>
                ))}
              </div>

              {/* Metrics */}
              <div className="flex gap-4 text-xs text-zinc-500">
                {p.metrics.total_trades != null && (
                  <span>Trades: {p.metrics.total_trades}</span>
                )}
                {p.metrics.win_rate != null && (
                  <span>WR: {p.metrics.win_rate.toFixed(1)}%</span>
                )}
                {p.metrics.avg_return != null && (
                  <span
                    className={
                      p.metrics.avg_return >= 0
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-red-600 dark:text-red-400'
                    }
                  >
                    Avg: {p.metrics.avg_return >= 0 ? '+' : ''}{p.metrics.avg_return.toFixed(2)}%
                  </span>
                )}
                {p.metrics.sharpe != null && <span>Sharpe: {p.metrics.sharpe.toFixed(2)}</span>}
                {p.metrics.robustness != null && (
                  <span>Robust: {p.metrics.robustness.toFixed(2)}</span>
                )}
              </div>

              {/* Actions */}
              {p.status === 'pending' && (
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => handleAction(p.id, 'approve')}
                    disabled={acting === p.id}
                    className="rounded bg-emerald-600 px-3 py-1 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleAction(p.id, 'reject')}
                    disabled={acting === p.id}
                    className="rounded bg-zinc-200 px-3 py-1 text-sm font-medium text-zinc-700 hover:bg-zinc-300 dark:bg-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-600 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
