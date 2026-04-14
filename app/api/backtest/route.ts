import { NextResponse } from 'next/server';
import { spawn } from 'child_process';
import { join } from 'path';

const BACKTEST_TIMEOUT_MS = 600_000; // 10 min max

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
        timeout: BACKTEST_TIMEOUT_MS,
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
