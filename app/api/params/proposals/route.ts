import { NextResponse } from 'next/server';
import { getSupabaseAdmin } from '@/lib/supabase';

/**
 * GET /api/params/proposals — list param proposals
 * PATCH /api/params/proposals — approve or reject a proposal
 */

export async function GET() {
  try {
    const sb = getSupabaseAdmin();
    const { data, error } = await sb
      .from('us_param_proposals')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(20);

    if (error) {
      return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
    return NextResponse.json({ success: true, data });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

interface PatchBody {
  id: string;
  action: 'approve' | 'reject';
}

export async function PATCH(req: Request) {
  try {
    const body = (await req.json()) as PatchBody;
    const { id, action } = body;

    if (!id || !['approve', 'reject'].includes(action)) {
      return NextResponse.json(
        { success: false, error: 'Invalid id or action' },
        { status: 400 },
      );
    }

    const sb = getSupabaseAdmin();

    const status = action === 'approve' ? 'approved' : 'rejected';
    const update: Record<string, unknown> = { status };
    if (action === 'approve') {
      update.approved_at = new Date().toISOString();
    }

    const { error } = await sb
      .from('us_param_proposals')
      .update(update)
      .eq('id', id)
      .eq('status', 'pending');

    if (error) {
      return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }

    return NextResponse.json({ success: true, status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
