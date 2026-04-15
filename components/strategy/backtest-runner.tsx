'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

type Status = 'idle' | 'pending' | 'running' | 'completed' | 'failed';

interface PollResponse {
  success: boolean;
  data?: {
    id: string;
    status: string;
    output: string | null;
    error: string | null;
  };
  error?: string;
}

export function BacktestRunner() {
  const [status, setStatus] = useState<Status>('idle');
  const [output, setOutput] = useState<string | null>(null);
  const [symbol, setSymbol] = useState('');
  const [days, setDays] = useState(365);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  async function runBacktest() {
    setStatus('pending');
    setOutput(null);
    stopPolling();

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

      const json = (await res.json()) as { success: boolean; data?: { id: string }; error?: string };

      if (!json.success || !json.data?.id) {
        setStatus('failed');
        setOutput(json.error ?? 'Failed to enqueue backtest');
        return;
      }

      const requestId = json.data.id;
      setOutput('Waiting for local executor to pick up the request...');

      // Poll every 3 seconds
      pollRef.current = setInterval(async () => {
        try {
          const pollRes = await fetch(`/api/backtest?id=${requestId}`);
          const pollJson = (await pollRes.json()) as PollResponse;

          if (!pollJson.success || !pollJson.data) return;

          const { status: reqStatus, output: reqOutput, error: reqError } = pollJson.data;

          if (reqStatus === 'running') {
            setStatus('running');
            setOutput('Backtest is running on local executor...');
          } else if (reqStatus === 'completed') {
            setStatus('completed');
            setOutput(reqOutput ?? 'Backtest completed');
            stopPolling();
          } else if (reqStatus === 'failed') {
            setStatus('failed');
            setOutput(reqError ?? 'Backtest failed');
            stopPolling();
          }
        } catch {
          // Polling error — keep trying
        }
      }, 3000);
    } catch (err: unknown) {
      setStatus('failed');
      setOutput(err instanceof Error ? err.message : 'Network error');
    }
  }

  const isRunning = status === 'pending' || status === 'running';

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
            disabled={isRunning}
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
            disabled={isRunning}
          />
        </div>
        <button
          onClick={runBacktest}
          disabled={isRunning}
          className={
            'inline-flex h-9 items-center gap-2 rounded-md px-4 text-sm font-medium text-white transition ' +
            (isRunning
              ? 'cursor-not-allowed bg-zinc-400'
              : 'bg-blue-600 hover:bg-blue-700 active:bg-blue-800')
          }
        >
          {isRunning ? (
            <>
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              {status === 'running' ? 'Running...' : 'Queued...'}
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
            (status === 'failed'
              ? 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300'
              : status === 'completed'
                ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                : 'bg-zinc-50 text-zinc-800 dark:bg-zinc-900 dark:text-zinc-300')
          }
        >
          {output}
        </pre>
      )}
    </div>
  );
}
