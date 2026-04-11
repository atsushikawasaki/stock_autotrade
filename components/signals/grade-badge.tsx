import { Badge } from '@/components/ui/badge';
import type { SignalGrade } from '@/lib/types/database';

const gradeVariant: Record<SignalGrade, 'success' | 'info' | 'warning' | 'danger'> = {
  A: 'success',
  B: 'info',
  C: 'warning',
  D: 'danger',
};

export function GradeBadge({ grade }: { grade: SignalGrade }) {
  return <Badge variant={gradeVariant[grade]}>{grade}</Badge>;
}
