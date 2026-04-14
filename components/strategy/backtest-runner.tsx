'use client';

import { useState } from 'react';

type Status = 'idle' | 'running' | 'success' | 'error';

interface BacktestResponse {
  success: boolean;
  data?: { output: string };
  error?: string;
}

export function BacktestRunner() {
  const [status, setStatus] = useState<Status>('idle');
  const [output, setOutput] = useState<string | null>(null);
  const [symbol, setSymbol] = useState('');
  const [days, setDays] = useState(365);

  async function runBacktest() {
    setStatus('running');
    setOutput(null);

    try {
      const body: Record<string, unknown> = { days };
      if (symbol.trim()) {
        body.symbol = symbol.trim().toUpperCase();
      }

      const res = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const json = (await res.json()) as BacktestResponse;

      if (json.success) {
        setStatus('success');
        setOutput(json.data?.output ?? 'Done');
      } else {
        setStatus('error');
        setOutput(json.error ?? 'Unknown error');
      }
    } catch (err: unknown) {
      setStatus('error');
      setOutput(err instanceof Error ? err.message : 'Network error');
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="bt-symbol" className="block text-xs font-medium text-zinc-500 mb-1">
            Symbol (空欄=全銘柄)
          </label>
          <input
            id="bt-symbol"
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="AAPL"
            className="h-9 w-28 rounded-md border border-zinc-300 bg-white px-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            disabled={status === 'running'}
          />
        </div>
        <div>
          <label htmlFor="bt-days" className="block text-xs font-medium text-zinc-500 mb-1">
            Lookback (days)
          </label>
          <input
            id="bt-days"
            type="number"
            value={days}
            onChange={(e) => setDays(Math.max(30, Math.min(3650, Number(e.target.value))))}
            className="h-9 w-20 rounded-md border border-zinc-300 bg-white px-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            disabled={status === 'running'}
          />
        </div>
        <button
          onClick={runBacktest}
          disabled={status === 'running'}
          className={
            'inline-flex h-9 items-center gap-2 rounded-md px-4 text-sm font-medium text-white transition ' +
            (status === 'running'
              ? 'cursor-not-allowed bg-zinc-400'
              : 'bg-blue-600 hover:bg-blue-700 active:bg-blue-800')
          }
        >
          {status === 'running' ? (
            <>
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              Running...
            </>
          ) : (
            'Run Backtest'
          )}
        </button>
      </div>

      {output && (
        <pre
          className={
            'max-h-80 overflow-auto rounded-md p-3 text-xs leading-relaxed ' +
            (status === 'error'
              ? 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300'
              : 'bg-zinc-50 text-zinc-800 dark:bg-zinc-900 dark:text-zinc-300')
          }
        >
          {output}
        </pre>
      )}
    </div>
  );
}
