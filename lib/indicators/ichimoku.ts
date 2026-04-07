export type IchimokuResult = {
  /** 転換線: (9-period high + 9-period low) / 2 */
  tenkan: (number | null)[];
  /** 基準線: (26-period high + 26-period low) / 2 */
  kijun: (number | null)[];
  /**
   * 先行スパンA: (転換線 + 基準線) / 2
   * Displayed 26 periods ahead — stored at index i+26 in this array.
   * Array length = n + 26 to accommodate future cloud projection.
   */
  senkouA: (number | null)[];
  /**
   * 先行スパンB: (52-period high + 52-period low) / 2
   * Displayed 26 periods ahead — stored at index i+26 in this array.
   * Array length = n + 26 to accommodate future cloud projection.
   */
  senkouB: (number | null)[];
  /**
   * 遅行スパン: close plotted 26 periods behind current.
   * chikou[i] = closes[i + 26] so it aligns visually with 26-bar-ago price.
   */
  chikou: (number | null)[];
};

function periodMidpoint(
  highs: number[],
  lows: number[],
  endIdx: number,
  period: number,
): number | null {
  const start = endIdx - period + 1;
  if (start < 0) return null;
  let high = highs[start];
  let low = lows[start];
  for (let i = start + 1; i <= endIdx; i++) {
    if (highs[i] > high) high = highs[i];
    if (lows[i] < low) low = lows[i];
  }
  return (high + low) / 2;
}

/**
 * Ichimoku Kinko Hyo (一目均衡表)
 *
 * Returns arrays of length n + 26 to include the 26-period forward cloud projection.
 * The first n values correspond to historical dates; the last 26 are future cloud.
 */
export function calcIchimoku(
  highs: number[],
  lows: number[],
  closes: number[],
  tenkanPeriod = 9,
  kijunPeriod = 26,
  senkouBPeriod = 52,
  displacement = 26,
): IchimokuResult {
  const n = closes.length;
  const total = n + displacement;

  const tenkan: (number | null)[] = new Array(total).fill(null);
  const kijun: (number | null)[] = new Array(total).fill(null);
  const senkouA: (number | null)[] = new Array(total).fill(null);
  const senkouB: (number | null)[] = new Array(total).fill(null);
  const chikou: (number | null)[] = new Array(total).fill(null);

  for (let i = 0; i < n; i++) {
    tenkan[i] = periodMidpoint(highs, lows, i, tenkanPeriod);
    kijun[i] = periodMidpoint(highs, lows, i, kijunPeriod);

    // 先行スパンA & B: placed displacement periods ahead
    const t = tenkan[i];
    const k = kijun[i];
    if (t !== null && k !== null) {
      senkouA[i + displacement] = (t + k) / 2;
    }
    senkouB[i + displacement] = periodMidpoint(highs, lows, i, senkouBPeriod);

    // 遅行スパン: close shifted 26 periods backward for display
    // chikou[i] = closes[i + displacement] means "close value, shown at past position"
    // In chart terms: chikou at index i shows close from i+displacement
    if (i + displacement < n) {
      chikou[i] = closes[i + displacement];
    }
  }

  return { tenkan, kijun, senkouA, senkouB, chikou };
}
