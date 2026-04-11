import { NextResponse } from 'next/server';
import { setStockActive } from '@/lib/queries/stocks';

interface ToggleBody {
  isActive: boolean;
}

function parseBody(body: unknown): ToggleBody | null {
  if (typeof body !== 'object' || body === null) return null;
  const obj = body as Record<string, unknown>;
  if (typeof obj.isActive !== 'boolean') return null;
  return { isActive: obj.isActive };
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ code: string }> },
) {
  try {
    const { code } = await params;
    if (!/^[A-Z0-9.\-]{1,10}$/i.test(code)) {
      return NextResponse.json(
        { success: false, error: 'Invalid stock code' },
        { status: 400 },
      );
    }
    const raw = (await req.json()) as unknown;
    const parsed = parseBody(raw);
    if (!parsed) {
      return NextResponse.json(
        { success: false, error: 'Invalid body: expected { isActive: boolean }' },
        { status: 400 },
      );
    }
    await setStockActive(code.toUpperCase(), parsed.isActive);
    return NextResponse.json({ success: true, data: { code, isActive: parsed.isActive } });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
