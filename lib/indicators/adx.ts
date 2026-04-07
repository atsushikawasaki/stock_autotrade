export type ADXResult = {
  adx: (number | null)[];
  plusDI: (number | null)[];
  minusDI: (number | null)[];
};

export function calcADX(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14
): ADXResult {
  const n = closes.length;
  const adx: (number | null)[] = new Array(n).fill(null);
  const plusDI: (number | null)[] = new Array(n).fill(null);
  const minusDI: (number | null)[] = new Array(n).fill(null);

  if (n < period * 2 + 1) return { adx, plusDI, minusDI };

  // Calculate raw +DM, -DM, TR
  const rawPlusDM: number[] = new Array(n).fill(0);
  const rawMinusDM: number[] = new Array(n).fill(0);
  const tr: number[] = new Array(n).fill(0);

  for (let i = 1; i < n; i++) {
    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    rawPlusDM[i] = upMove > downMove && upMove > 0 ? upMove : 0;
    rawMinusDM[i] = downMove > upMove && downMove > 0 ? downMove : 0;
    const hl = highs[i] - lows[i];
    const hpc = Math.abs(highs[i] - closes[i - 1]);
    const lpc = Math.abs(lows[i] - closes[i - 1]);
    tr[i] = Math.max(hl, hpc, lpc);
  }

  // Wilder's smoothed values for the first period
  let smoothTR = tr.slice(1, period + 1).reduce((a, b) => a + b, 0);
  let smoothPlusDM = rawPlusDM.slice(1, period + 1).reduce((a, b) => a + b, 0);
  let smoothMinusDM = rawMinusDM.slice(1, period + 1).reduce((a, b) => a + b, 0);

  const calcDI = (dm: number, smoothedTR: number) =>
    smoothedTR === 0 ? 0 : (dm / smoothedTR) * 100;

  let sumDX = 0;
  const dxBuffer: number[] = [];

  for (let i = period; i < n; i++) {
    if (i > period) {
      smoothTR = smoothTR - smoothTR / period + tr[i];
      smoothPlusDM = smoothPlusDM - smoothPlusDM / period + rawPlusDM[i];
      smoothMinusDM = smoothMinusDM - smoothMinusDM / period + rawMinusDM[i];
    }

    const pdi = calcDI(smoothPlusDM, smoothTR);
    const mdi = calcDI(smoothMinusDM, smoothTR);
    plusDI[i] = pdi;
    minusDI[i] = mdi;

    const diSum = pdi + mdi;
    const dx = diSum === 0 ? 0 : (Math.abs(pdi - mdi) / diSum) * 100;
    dxBuffer.push(dx);

    // ADX is Wilder's smoothing of DX, needs `period` DX values to seed
    if (dxBuffer.length === period) {
      adx[i] = dxBuffer.reduce((a, b) => a + b, 0) / period;
    } else if (dxBuffer.length > period) {
      adx[i] = ((adx[i - 1] as number) * (period - 1) + dx) / period;
    }
  }

  return { adx, plusDI, minusDI };
}
