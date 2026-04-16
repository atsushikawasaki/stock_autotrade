'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

type Status = 'idle' | 'pending' | 'running' | 'completed' | 'failed';
type Mode = 'backtest' | 'optimize';

interface PollData {
  id: string;
  status: string;
  output: string | null;
  error: string | null;
}

function useBacktestQueue() {
  const [status, setStatus] = useState<Status>('idle');
  const [output, setOutput] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    pollCountRef.current = 0;
  }, []);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  const enqueue = useCallback(async (body: Record<string, unknown>) => {
    setStatus('pending');
    setOutput('Enqueueing request...');
    stopPolling();

    try {
      const res = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        setStatus('failed');
        setOutput(`API error: ${res.status} ${res.statusText}`);
        return;
      }

      const json = (await res.json()) as { success: boolean; data?: { id: string }; error?: string };

      if (!json.success || !json.data?.id) {
        setStatus('failed');
        setOutput(json.error ?? 'Failed to enqueue request');
        return;
      }

      const requestId = json.data.id;
      setOutput('Waiting for local executor to pick up the request...');
      pollCountRef.current = 0;

      pollRef.current = setInterval(async () => {
        pollCountRef.current += 1;

        if (pollCountRef.current > 200) {
          setStatus('failed');
          setOutput('Timeout: did not complete within 10 minutes');
          stopPolling();
          return;
        }

        try {
          const pollRes = await fetch(`/api/backtest?id=${requestId}`, {
            credentials: 'include',
          });

          if (!pollRes.ok) {
            if (pollCountRef.current > 5) {
              setOutput(`Polling error: ${pollRes.status} (retrying...)`);
            }
            return;
          }

          const pollJson = (await pollRes.json()) as { success: boolean; data?: PollData };
          if (!pollJson.success || !pollJson.data) return;

          const { status: reqStatus, output: reqOutput, error: reqError } = pollJson.data;

          if (reqStatus === 'running') {
            setStatus('running');
            setOutput('Running on local executor...');
          } else if (reqStatus === 'completed') {
            setStatus('completed');
            setOutput(reqOutput ?? 'Completed (no output)');
            stopPolling();
          } else if (reqStatus === 'failed') {
            setStatus('failed');
            setOutput(reqError ?? 'Failed');
            stopPolling();
          }
        } catch {
          // Network error — keep trying
        }
      }, 3000);
    } catch (err: unknown) {
      setStatus('failed');
      setOutput(err instanceof Error ? err.message : 'Network error');
    }
  }, [stopPolling]);

  const isRunning = status === 'pending' || status === 'running';
  return { status, output, isRunning, enqueue };
}

export function BacktestRunner() {
  const [mode, setMode] = useState<Mode>('backtest');
  const [symbol, setSymbol] = useState('');
  const [days, setDays] = useState(365);
  const [maxCombos, setMaxCombos] = useState(50);
  const [sampleStocks, setSampleStocks] = useState(20);
  const { status, output, isRunning, enqueue } = useBacktestQueue();

  function handleRun() {
    const body: Record<string, unknown> = { days };

    if (mode === 'optimize') {
      body.mode = 'optimize';
      body.max_combos = maxCombos;
      body.sample_stocks = sampleStocks;
    } else if (symbol.trim()) {
      body.symbol = symbol.trim().toUpperCase();
    }

    enqueue(body);
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 mb-2">
        <button
          onClick={() => setMode('backtest')}
          disabled={isRunning}
          className={
            'rounded-md px-3 py-1 text-xs font-medium transition ' +
            (mode === 'backtest'
              ? 'bg-blue-600 text-white'
              : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-400')
          }
        >
          Backtest
        </button>
        <button
          onClick={() => setMode('optimize')}
          disabled={isRunning}
          className={
            'rounded-md px-3 py-1 text-xs font-medium transition ' +
            (mode === 'optimize'
              ? 'bg-purple-600 text-white'
              : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-400')
          }
        >
          Optimize
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        {mode === 'backtest' && (
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
        )}
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
        {mode === 'optimize' && (
          <>
            <div>
              <label htmlFor="bt-combos" className="block text-xs font-medium text-zinc-500 mb-1">
                Max combos
              </label>
              <input
                id="bt-combos"
                type="number"
                value={maxCombos}
                onChange={(e) => setMaxCombos(Math.max(1, Math.min(200, Number(e.target.value))))}
                className="h-9 w-20 rounded-md border border-zinc-300 bg-white px-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                disabled={isRunning}
              />
            </div>
            <div>
              <label htmlFor="bt-sample" className="block text-xs font-medium text-zinc-500 mb-1">
                Sample stocks
              </label>
              <input
                id="bt-sample"
                type="number"
                value={sampleStocks}
                onChange={(e) => setSampleStocks(Math.max(1, Math.min(50, Number(e.target.value))))}
                className="h-9 w-20 rounded-md border border-zinc-300 bg-white px-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                disabled={isRunning}
              />
            </div>
          </>
        )}
        <button
          onClick={handleRun}
          disabled={isRunning}
          className={
            'inline-flex h-9 items-center gap-2 rounded-md px-4 text-sm font-medium text-white transition ' +
            (isRunning
              ? 'cursor-not-allowed bg-zinc-400'
              : mode === 'optimize'
                ? 'bg-purple-600 hover:bg-purple-700 active:bg-purple-800'
                : 'bg-blue-600 hover:bg-blue-700 active:bg-blue-800')
          }
        >
          {isRunning ? (
            <>
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              {status === 'running' ? 'Running...' : 'Queued...'}
            </>
          ) : mode === 'optimize' ? (
            'Run Optimization'
          ) : (
            'Run Backtest'
          )}
        </button>
      </div>

      {output && (
        <pre
          className={
            'max-h-80 overflow-auto rounded-md p-3 text-xs leading-relaxed whitespace-pre-wrap ' +
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
