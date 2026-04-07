import { calcSMA } from '@/lib/indicators';

export type StochasticResult = {
  k: (number | null)[];
  d: (number | null)[];
  /** J = 3K - 2D (KDJ J-line: amplifies overbought/oversold extremes) */
  j: (number | null)[];
};

export function calcStochastic(
  highs: number[],
  lows: number[],
  closes: number[],
  kPeriod = 14,
  dPeriod = 3
): StochasticResult {
  const n = closes.length;
  const rawK: (number | null)[] = new Array(n).fill(null);

  for (let i = kPeriod - 1; i < n; i++) {
    const slice_h = highs.slice(i - kPeriod + 1, i + 1);
    const slice_l = lows.slice(i - kPeriod + 1, i + 1);
    const highest = Math.max(...slice_h);
    const lowest = Math.min(...slice_l);
    const range = highest - lowest;
    rawK[i] = range === 0 ? 50 : ((closes[i] - lowest) / range) * 100;
  }

  // %D is SMA of %K (only over non-null values)
  const kNotNull = rawK.filter((v): v is number => v !== null);
  const dOfK = calcSMA(kNotNull, dPeriod);

  const d: (number | null)[] = new Array(n).fill(null);
  let idx = 0;
  for (let i = 0; i < n; i++) {
    if (rawK[i] !== null) {
      d[i] = dOfK[idx++] ?? null;
    }
  }

  // J = 3K - 2D
  const j: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    const kv = rawK[i];
    const dv = d[i];
    j[i] = kv !== null && dv !== null ? 3 * kv - 2 * dv : null;
  }

  return { k: rawK, d, j };
}
