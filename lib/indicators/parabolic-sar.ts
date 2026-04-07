export type ParabolicSARResult = {
  sar: (number | null)[];
  trend: ('bull' | 'bear' | null)[];
};

/**
 * Parabolic SAR (Stop and Reverse)
 *
 * Classic Wilder formula:
 *   SAR[i] = SAR[i-1] + AF × (EP - SAR[i-1])
 *   AF: starts at 0.02, increments by 0.02 each time EP is updated, max 0.20
 *   EP: Extreme Point — highest high in bull, lowest low in bear
 *
 * Reversal: in bull, price falls below SAR → switch to bear (and vice versa)
 */
export function calcParabolicSAR(
  highs: number[],
  lows: number[],
  afStep = 0.02,
  afMax = 0.20,
): ParabolicSARResult {
  const n = highs.length;
  const sar: (number | null)[] = new Array(n).fill(null);
  const trend: ('bull' | 'bear' | null)[] = new Array(n).fill(null);

  if (n < 2) return { sar, trend };

  // Seed: use first 2 bars to determine initial trend
  let isBull = highs[1] >= highs[0];
  let af = afStep;
  let ep = isBull ? highs[1] : lows[1];
  let prevSar = isBull ? Math.min(lows[0], lows[1]) : Math.max(highs[0], highs[1]);

  sar[1] = prevSar;
  trend[1] = isBull ? 'bull' : 'bear';

  for (let i = 2; i < n; i++) {
    let newSar = prevSar + af * (ep - prevSar);

    if (isBull) {
      // In bull: SAR must not exceed prior two lows
      newSar = Math.min(newSar, lows[i - 1], lows[i - 2]);

      if (lows[i] < newSar) {
        // Reversal to bear
        isBull = false;
        newSar = ep; // SAR becomes the highest EP
        ep = lows[i];
        af = afStep;
      } else {
        if (highs[i] > ep) {
          ep = highs[i];
          af = Math.min(af + afStep, afMax);
        }
      }
    } else {
      // In bear: SAR must not be below prior two highs
      newSar = Math.max(newSar, highs[i - 1], highs[i - 2]);

      if (highs[i] > newSar) {
        // Reversal to bull
        isBull = true;
        newSar = ep; // SAR becomes the lowest EP
        ep = highs[i];
        af = afStep;
      } else {
        if (lows[i] < ep) {
          ep = lows[i];
          af = Math.min(af + afStep, afMax);
        }
      }
    }

    sar[i] = newSar;
    trend[i] = isBull ? 'bull' : 'bear';
    prevSar = newSar;
  }

  return { sar, trend };
}
