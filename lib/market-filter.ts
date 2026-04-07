import { calcSMA } from '@/lib/indicators';
import { MARKET_INDEX_SYMBOL, MARKET_SMA_FAST, MARKET_SMA_SLOW, HISTORY_DAYS_ANALYSIS } from '@/lib/constants';
import { fetchDailyPrices } from '@/lib/yahoo-client';

export type MarketRegime = 'bull' | 'bear' | 'neutral';

let cachedRegime: { regime: MarketRegime; fetchedAt: number } | null = null;
const CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour

export async function getMarketRegime(): Promise<MarketRegime> {
  if (cachedRegime && Date.now() - cachedRegime.fetchedAt < CACHE_TTL_MS) {
    return cachedRegime.regime;
  }

  try {
    const prices = await fetchDailyPrices(MARKET_INDEX_SYMBOL, HISTORY_DAYS_ANALYSIS + MARKET_SMA_SLOW);
    if (prices.length < MARKET_SMA_SLOW) return 'neutral';

    const closes = prices.map((p) => p.close);
    const smaFast = calcSMA(closes, MARKET_SMA_FAST);
    const smaSlow = calcSMA(closes, MARKET_SMA_SLOW);

    const last = closes.length - 1;
    const fastVal = smaFast[last];
    const slowVal = smaSlow[last];

    if (fastVal === null || slowVal === null) return 'neutral';

    const regime: MarketRegime = fastVal > slowVal ? 'bull' : 'bear';
    cachedRegime = { regime, fetchedAt: Date.now() };
    return regime;
  } catch (error) {
    console.error('Failed to determine market regime:', error);
    return 'neutral';
  }
}
