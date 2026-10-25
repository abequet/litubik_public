import { cn } from '@/lib/utils'

export interface SegmentedOption<T extends string | number> {
  value: T
  label: React.ReactNode
  title?: string
}

/** Pill-style single-select toggle (round selectors, open/resolved views, …).
 * Replaces the hand-rolled `rounded-full bg-primary/bg-muted` toggles that were
 * copy-pasted across the app. */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  size = 'default',
  className,
}: {
  options: SegmentedOption<T>[]
  value: T
  onChange: (v: T) => void
  size?: 'sm' | 'default'
  className?: string
}) {
  return (
    <div className={cn('inline-flex items-center gap-1', className)}>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={String(o.value)}
            type="button"
            title={o.title}
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={cn(
              'rounded-full font-medium transition-colors outline-none cursor-pointer',
              'focus-visible:ring-ring/50 focus-visible:ring-[3px]',
              size === 'sm' ? 'px-2.5 py-0.5 text-xs' : 'px-3 py-1 text-xs',
              active
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
