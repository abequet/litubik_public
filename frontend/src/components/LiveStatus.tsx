// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { cn } from '@/lib/utils'

/** Always-mounted polite live region (WCAG 4.1.3): an error or status
 * message rendered here is announced by screen readers without moving the
 * focus. It stays in the DOM even when empty — a region inserted together
 * with its text is often not announced — and takes no space while empty
 * (the margin classes only apply when there is a message). */
export default function LiveStatus({ children, tone = 'error', className }: {
  children?: React.ReactNode
  tone?: 'error' | 'info'
  className?: string
}) {
  return (
    <p role="status" aria-live="polite" aria-atomic="true"
       className={cn(tone === 'error' ? 'text-destructive' : 'text-muted-foreground',
         children ? className : 'm-0 h-0 overflow-hidden')}>
      {children}
    </p>
  )
}
