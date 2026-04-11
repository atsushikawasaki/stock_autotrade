'use client';

import { useState, useTransition } from 'react';
import { Switch } from '@/components/ui/switch';
import { TR, TD } from '@/components/ui/table';
import type { Stock } from '@/lib/types/database';

interface Props {
  stock: Stock;
}

export function StockToggleRow({ stock }: Props) {
  const [active, setActive] = useState(stock.is_active);
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const toggle = (next: boolean) => {
    setError(null);
    const prev = active;
    setActive(next);
    startTransition(async () => {
      try {
        const res = await fetch(`/api/stocks/${stock.code}/toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ isActive: next }),
        });
        const json = (await res.json()) as { success: boolean; error?: string };
        if (!res.ok || !json.success) {
          throw new Error(json.error ?? `HTTP ${res.status}`);
        }
      } catch (e: unknown) {
        setActive(prev);
        setError(e instanceof Error ? e.message : 'Toggle failed');
      }
    });
  };

  return (
    <TR>
      <TD className="font-medium">{stock.code}</TD>
      <TD className="text-zinc-600 dark:text-zinc-400">{stock.name ?? '—'}</TD>
      <TD className="text-zinc-500">{stock.sector ?? '—'}</TD>
      <TD>
        <div className="flex items-center gap-3">
          <Switch
            checked={active}
            onChange={toggle}
            disabled={isPending}
            aria-label={`Toggle ${stock.code}`}
          />
          <span className="text-xs text-zinc-500">{active ? 'active' : 'inactive'}</span>
          {error ? <span className="text-xs text-red-500">{error}</span> : null}
        </div>
      </TD>
    </TR>
  );
}
