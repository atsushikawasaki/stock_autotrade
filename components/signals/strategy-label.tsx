import { Badge } from '@/components/ui/badge';
import type { SignalStrategy } from '@/lib/types/database';

const labels: Record<SignalStrategy, string> = {
  strategy_a: 'A · Breakout',
  strategy_b: 'B · Reversal',
  strategy_c: 'C · GoldenCross',
};

export function StrategyLabel({ strategy }: { strategy: SignalStrategy }) {
  return <Badge variant="neutral">{labels[strategy] ?? strategy}</Badge>;
}
