import { NextResponse } from 'next/server';
import { getSupabaseAdmin } from '@/lib/supabase';

/**
 * GET /api/positions/prices?codes=AAPL,MSFT
 * Returns latest close price for each stock code from us_daily_prices.
 */
export async function GET(req: Request) {
  try {
    const url = new URL(req.url);
    const codesParam = url.searchParams.get('codes');

    if (!codesParam) {
      return NextResponse.json({ success: false, error: 'Missing codes parameter' }, { status: 400 });
    }

    const codes = codesParam
      .split(',')
      .map((c) => c.trim().toUpperCase())
      .filter((c) => /^[A-Z0-9.\-]{1,10}$/.test(c));

    if (codes.length === 0) {
      return NextResponse.json({ success: true, data: {} });
    }

    const sb = getSupabaseAdmin();

    // Get the latest price for each stock code
    // Use a raw query to get the most recent trade_date per code
    const prices: Record<string, number> = {};

    for (const code of codes) {
      const { data, error } = await sb
        .from('us_daily_prices')
        .select('close')
        .eq('stock_code', code)
        .order('trade_date', { ascending: false })
        .limit(1)
        .single();

      if (!error && data) {
        prices[code] = data.close;
      }
    }

    return NextResponse.json({ success: true, data: prices });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
