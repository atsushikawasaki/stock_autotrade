import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';

interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon?: LucideIcon;
  tone?: 'default' | 'positive' | 'negative';
}

const toneClasses: Record<NonNullable<KpiCardProps['tone']>, string> = {
  default: 'text-zinc-900 dark:text-zinc-100',
  positive: 'text-emerald-600 dark:text-emerald-400',
  negative: 'text-red-600 dark:text-red-400',
};

export function KpiCard({ title, value, subtitle, icon: Icon, tone = 'default' }: KpiCardProps) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between pb-2">
        <CardTitle>{title}</CardTitle>
        {Icon ? <Icon className="h-4 w-4 text-zinc-400" /> : null}
      </CardHeader>
      <CardContent>
        <div className={cn('text-2xl font-semibold tracking-tight', toneClasses[tone])}>
          {value}
        </div>
        {subtitle ? (
          <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{subtitle}</div>
        ) : null}
      </CardContent>
    </Card>
  );
}
