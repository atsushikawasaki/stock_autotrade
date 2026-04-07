import { calcSMA } from '@/lib/indicators';

export type BollingerBands = {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
};

export function calcBollingerBands(
  closes: number[],
  period = 20,
  stdDevMult = 2
): BollingerBands {
  const middle = calcSMA(closes, period);
  const upper: (number | null)[] = new Array(closes.length).fill(null);
  const lower: (number | null)[] = new Array(closes.length).fill(null);

  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1);
    const mean = middle[i] as number;
    const variance = slice.reduce((sum, v) => sum + (v - mean) ** 2, 0) / period;
    const sd = Math.sqrt(variance);
    upper[i] = mean + stdDevMult * sd;
    lower[i] = mean - stdDevMult * sd;
  }

  return { upper, middle, lower };
}
