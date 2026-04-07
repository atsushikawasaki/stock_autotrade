import YahooFinance from 'yahoo-finance2';
import type { PriceRow } from '@/lib/price-cache';

const yahooFinance = new YahooFinance({
  suppressNotices: ['ripHistorical', 'yahooSurvey'],
});

/**
 * Fetch daily OHLCV from Yahoo Finance for a US stock.
 * @param symbol - Yahoo Finance symbol (e.g. 'AAPL', 'MSFT', 'SPY')
 * @param days - Number of calendar days of history to fetch
 */
export async function fetchDailyPrices(symbol: string, days: number): Promise<PriceRow[]> {
  const period1 = new Date();
  period1.setDate(period1.getDate() - days);

  const result = await yahooFinance.chart(symbol, { period1, interval: '1d' });
  const rows = result.quotes ?? [];

  return rows
    .filter((r) => r.close != null)
    .map((r) => ({
      date: new Date(r.date).toISOString().split('T')[0],
      open: r.open ?? r.close as number,
      high: r.high ?? null,
      low: r.low ?? null,
      close: r.close as number,
      volume: r.volume ?? 0,
    }));
}
