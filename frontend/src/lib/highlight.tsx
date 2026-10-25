// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Shared text highlighter (T14): several word families, each with its own
 * mark style — the equations' keywords (neutral) plus the project's
 * hand-curated green/red lists. Earlier families win when a word appears in
 * several lists, so pass red/green before the neutral keywords. */

export interface HighlightFamily {
  words: string[]
  className: string
}

export const HL_NEUTRAL = 'rounded-sm bg-foreground/15 px-0.5 text-foreground'
export const HL_GREEN =
  'rounded-sm bg-success/25 px-0.5 text-foreground'
export const HL_RED =
  'rounded-sm bg-destructive/25 px-0.5 text-foreground'
// ticket #8: terms of the screening list's keyword search
export const HL_SEARCH =
  'rounded-sm bg-warning/40 px-0.5 font-medium text-foreground'

const escape = (w: string) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

export function highlight(text: string, families: HighlightFamily[]) {
  const cleaned = families
    .map((f) => ({
      className: f.className,
      words: f.words.map((w) => w.trim()).filter((w) => w.length > 2),
    }))
    .filter((f) => f.words.length > 0)
  if (!cleaned.length || !text) return text
  const all = cleaned.flatMap((f) => f.words.map(escape))
  const splitter = new RegExp(`(${all.join('|')})`, 'gi')
  const matchers = cleaned.map((f) => ({
    className: f.className,
    re: new RegExp(`^(${f.words.map(escape).join('|')})$`, 'i'),
  }))
  // split with a capture group: odd indices are the matched words
  return text.split(splitter).map((part, i) => {
    if (i % 2 === 0) return part
    const family = matchers.find((m) => m.re.test(part))
    return (
      <mark key={i} className={family?.className ?? HL_NEUTRAL}>
        {part}
      </mark>
    )
  })
}
