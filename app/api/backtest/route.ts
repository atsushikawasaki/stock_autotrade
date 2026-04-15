import { NextResponse } from 'next/server';
import { getSupabaseAdmin } from '@/lib/supabase';

/**
 * POST /api/backtest — enqueue a backtest request
 * GET  /api/backtest?id=xxx — poll for status
 */

interface BacktestParams {
  symbol?: string;
  days?: number;
}

function parseBody(body: unknown): BacktestParams {
  if (typeof body !== 'object' || body === null) return {};
  const obj = body as Record<string, unknown>;
  const params: BacktestParams = {};
  if (typeof obj.symbol === 'string' && /^[A-Z0-9.\-]{1,10}$/i.test(obj.symbol)) {
    params.symbol = obj.symbol.toUpperCase();
  }
  if (typeof obj.days === 'number' && obj.days > 0 && obj.days <= 3650) {
    params.days = Math.floor(obj.days);
  }
  return params;
}

export async function POST(req: Request) {
  try {
    const raw = (await req.json().catch(() => ({}))) as unknown;
    const params = parseBody(raw);

    const sb = getSupabaseAdmin();
    const { data, error } = await sb
      .from('us_backtest_requests')
      .insert({ status: 'pending', params })
      .select('id')
      .single();

    if (error) {
      return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }

    return NextResponse.json({ success: true, data: { id: data.id } });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

export async function GET(req: Request) {
  try {
    const url = new URL(req.url);
    const id = url.searchParams.get('id');

    if (!id) {
      return NextResponse.json({ success: false, error: 'Missing id parameter' }, { status: 400 });
    }

    const sb = getSupabaseAdmin();
    const { data, error } = await sb
      .from('us_backtest_requests')
      .select('id, status, output, error, created_at, started_at, completed_at')
      .eq('id', id)
      .single();

    if (error) {
      return NextResponse.json({ success: false, error: error.message }, { status: 404 });
    }

    return NextResponse.json({ success: true, data });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
