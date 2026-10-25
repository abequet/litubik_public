import * as React from 'react'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cn } from '@/lib/utils'

function Tabs({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn('flex flex-col gap-2', className)}
      {...props}
    />
  )
}

/** Underline tab bar (Linear-style): flat, a thin accent rule under the active
 * tab. Sits on the page, not in a filled container. */
function TabsList({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        'inline-flex items-center gap-1 border-b border-border w-full',
        className,
      )}
      {...props}
    />
  )
}

function TabsTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  // Several pages use the tab bar alone and render the active section
  // themselves, so Radix's aria-controls would name a panel that does not
  // exist (axe: aria-valid-attr-value). Keep it only when the panel is there.
  const ref = React.useRef<HTMLButtonElement>(null)
  React.useEffect(() => {
    const el = ref.current
    const id = el?.getAttribute('aria-controls')
    if (el && id && !document.getElementById(id)) el.removeAttribute('aria-controls')
  })
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      data-slot="tabs-trigger"
      className={cn(
        'relative inline-flex items-center gap-1.5 px-4 py-2 -mb-px text-sm font-medium text-muted-foreground transition-colors',
        'hover:text-foreground disabled:pointer-events-none disabled:opacity-50',
        'outline-none focus-visible:ring-ring/50 focus-visible:ring-[3px] rounded-sm',
        'data-[state=active]:text-foreground data-[state=active]:font-semibold',
        "data-[state=active]:after:content-[''] data-[state=active]:after:absolute data-[state=active]:after:inset-x-2 data-[state=active]:after:-bottom-px data-[state=active]:after:h-0.5 data-[state=active]:after:rounded-full data-[state=active]:after:bg-primary",
        className,
      )}
      {...props}
    />
  )
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn('flex-1 outline-none', className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
