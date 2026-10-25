import { cn } from '@/lib/utils'

/** A single metric tile: big tabular number over a muted label. Used on the
 * dashboards. `tone` colours the value with a (desaturated) vote colour. */
export function Stat({
  value,
  label,
  tone,
  className,
}: {
  value: React.ReactNode
  label: React.ReactNode
  tone?: 'success' | 'warning' | 'destructive'
  className?: string
}) {
  return (
    <div className={cn('flex flex-col', className)}>
      <span
        className={cn(
          'text-2xl font-semibold tabular-nums tracking-tight',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'destructive' && 'text-destructive',
        )}
      >
        {value}
      </span>
      <span className="text-xs text-muted-foreground mt-0.5">{label}</span>
    </div>
  )
}
