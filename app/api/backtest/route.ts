import { NextResponse } from 'next/server';

/**
 * Backtest API — runs executor/backtest.py via child_process.
 * Only works in local/self-hosted environments (not Vercel serverless).
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
  // Dynamic import to avoid bundling child_process in serverless
  let spawn: typeof import('child_process').spawn;
  let join: typeof import('path').join;
  try {
    const cp = await import('child_process');
    const path = await import('path');
    spawn = cp.spawn;
    join = path.join;
  } catch {
    return NextResponse.json(
      { success: false, error: 'Backtest is only available in local environment (not Vercel)' },
      { status: 501 },
    );
  }

  try {
    const raw = (await req.json().catch(() => ({}))) as unknown;
    const params = parseBody(raw);

    const executorDir = join(process.cwd(), 'executor');
    const args = [join(executorDir, 'backtest.py'), '--save'];
    if (params.symbol) {
      args.push('--symbol', params.symbol);
    }
    if (params.days) {
      args.push('--days', String(params.days));
    }

    const output = await new Promise<string>((resolve, reject) => {
      const chunks: string[] = [];
      const proc = spawn('python3', args, {
        cwd: executorDir,
        timeout: 600_000,
        env: { ...process.env },
      });

      proc.stdout.on('data', (data: Buffer) => {
        chunks.push(data.toString());
      });
      proc.stderr.on('data', (data: Buffer) => {
        chunks.push(data.toString());
      });
      proc.on('close', (code) => {
        const text = chunks.join('');
        if (code === 0) {
          resolve(text);
        } else {
          reject(new Error(`Backtest exited with code ${code}:\n${text.slice(-2000)}`));
        }
      });
      proc.on('error', (err) => {
        reject(new Error(`Failed to start backtest: ${err.message}`));
      });
    });

    return NextResponse.json({
      success: true,
      data: { output: output.slice(-5000) },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { success: false, error: message.slice(-2000) },
      { status: 500 },
    );
  }
}
