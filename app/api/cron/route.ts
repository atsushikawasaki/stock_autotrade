import { NextResponse } from 'next/server';
import { getSupabaseAdmin } from '@/lib/supabase';
import { getActiveStocks } from '@/lib/stock-universe';
import { getMarketRegime } from '@/lib/market-filter';
import { fetchDailyPrices } from '@/lib/yahoo-client';
import { evaluateAllStrategies } from '@/lib/strategies';
import { sendLineMessage } from '@/lib/line';
import { HISTORY_DAYS_ANALYSIS, NOTIFY_GRADES, MIN_NOTIFY_INTERVAL_HOURS } from '@/lib/constants';
import type { PriceRow } from '@/lib/price-cache';

const BATCH_SIZE = 10;

export async function GET(request: Request) {
  const authHeader = request.headers.get('authorization');
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    const stocks = await getActiveStocks();
    if (stocks.length === 0) {
      return NextResponse.json({ message: 'No active stocks' });
    }

    const marketRegime = await getMarketRegime();
    const signalsSummary: Array<{
      code: string;
      name: string | null;
      strategy: string;
      grade: string;
      score: number;
    }> = [];
    let analyzed = 0;
    let signalsFound = 0;

    // Process in batches
    for (let i = 0; i < stocks.length; i += BATCH_SIZE) {
      const batch = stocks.slice(i, i + BATCH_SIZE);

      await Promise.all(
        batch.map(async (stock) => {
          try {
            const prices = await fetchDailyPrices(stock.code, HISTORY_DAYS_ANALYSIS);
            analyzed++;

            if (prices.length < 80) return; // Need enough history for SMA75

            const signals = evaluateAllStrategies(prices, marketRegime);

            for (const sig of signals) {
              if (!sig.triggered) continue;

              // Check notification throttle
              const shouldNotify = await checkNotifyThrottle(stock.code, sig.strategy);

              // Upsert signal to DB
              const { error } = await getSupabaseAdmin()
                .from('us_signals')
                .upsert({
                  stock_code: stock.code,
                  signal_date: new Date().toISOString().split('T')[0],
                  strategy: sig.strategy,
                  direction: 'buy',
                  score: sig.score,
                  grade: sig.grade,
                  entry_price: sig.entryPrice,
                  stop_loss: sig.stopLoss,
                  take_profit: sig.takeProfit,
                  indicators: sig.indicators,
                  reason: sig.reason,
                  status: 'pending',
                  notified: shouldNotify,
                }, { onConflict: 'stock_code,signal_date,strategy' });

              if (error) {
                console.error(`Signal upsert failed for ${stock.code}:`, error);
                continue;
              }

              signalsFound++;
              signalsSummary.push({
                code: stock.code,
                name: stock.name,
                strategy: sig.strategy,
                grade: sig.grade,
                score: sig.score,
              });

              // Send LINE notification
              if (shouldNotify && NOTIFY_GRADES.includes(sig.grade)) {
                await sendSignalNotification(stock, sig, prices);
              }
            }
          } catch (err) {
            console.error(`Error processing ${stock.code}:`, err);
          }
        })
      );
    }

    // Send summary if any signals found
    if (signalsSummary.length > 0) {
      const summaryText = [
        `[US Stock] Signal Summary (${marketRegime})`,
        `Analyzed: ${analyzed} / Signals: ${signalsFound}`,
        '',
        ...signalsSummary.map((s) =>
          `${s.grade} ${s.code} (${s.name}) ${s.strategy.replace('strategy_', '').toUpperCase()} score:${s.score}`
        ),
      ].join('\n');
      await sendLineMessage(summaryText);
    }

    return NextResponse.json({
      analyzed,
      signalsFound,
      marketRegime,
      signals: signalsSummary,
    });
  } catch (error) {
    console.error('Cron error:', error);
    return NextResponse.json({ error: 'Internal error' }, { status: 500 });
  }
}

async function checkNotifyThrottle(stockCode: string, strategy: string): Promise<boolean> {
  const cutoff = new Date(Date.now() - MIN_NOTIFY_INTERVAL_HOURS * 60 * 60 * 1000).toISOString();

  const { data } = await getSupabaseAdmin()
    .from('us_signals')
    .select('id')
    .eq('stock_code', stockCode)
    .eq('strategy', strategy)
    .eq('notified', true)
    .gte('created_at', cutoff)
    .limit(1);

  return !data || data.length === 0;
}

async function sendSignalNotification(
  stock: { code: string; name: string | null },
  sig: { strategy: string; grade: string; score: number; entryPrice: number; stopLoss: number | null; takeProfit: number | null; reason: string },
  prices: PriceRow[],
): Promise<void> {
  const strategyLabel = sig.strategy.replace('strategy_', '').toUpperCase();
  const last = prices[prices.length - 1];

  const text = [
    `[${sig.grade}] ${stock.code} ${stock.name ?? ''}`,
    `Strategy ${strategyLabel} / Score: ${sig.score}`,
    `Entry: $${sig.entryPrice.toFixed(2)}`,
    sig.stopLoss ? `SL: $${sig.stopLoss.toFixed(2)}` : '',
    sig.takeProfit ? `TP: $${sig.takeProfit.toFixed(2)}` : '',
    `Volume: ${last.volume.toLocaleString()}`,
    '',
    sig.reason,
  ].filter(Boolean).join('\n');

  await sendLineMessage(text);
}
