// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Type } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'

/** T12: app-wide text size, as a % of the default. The whole UI is sized in
 * rem, so setting the root font-size scales everything; persisted per
 * browser in localStorage. */

const KEY = 'litubik-font-scale'
const MIN = 80
const MAX = 140

export function applyStoredFontScale() {
  const stored = Number(localStorage.getItem(KEY))
  if (stored >= MIN && stored <= MAX && stored !== 100) {
    document.documentElement.style.fontSize = `${stored}%`
  }
}

export default function FontSizeControl() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [scale, setScale] = useState(() => {
    const stored = Number(localStorage.getItem(KEY))
    return stored >= MIN && stored <= MAX ? stored : 100
  })
  const popRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    document.documentElement.style.fontSize =
      scale === 100 ? '' : `${scale}%`
    localStorage.setItem(KEY, String(scale))
  }, [scale])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!popRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [open])

  return (
    <div className="relative" ref={popRef}>
      <Button variant="ghost" size="icon" title={t('Text size')}
              aria-label={t('Text size')}
              onClick={() => setOpen((v) => !v)}>
        <Type className="size-4" />
      </Button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-border bg-popover p-3 text-popover-foreground shadow-lg">
          <p className="mb-2 flex items-baseline justify-between text-xs font-medium">
            {t('Text size')}
            <span className="tabular-nums text-muted-foreground">{scale}%</span>
          </p>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">A</span>
            <Slider min={MIN} max={MAX} step={5} value={[scale]}
                    onValueChange={([v]) => setScale(v)} />
            <span className="text-base text-muted-foreground">A</span>
          </div>
          <Button variant="ghost" size="sm"
                  className="mt-2 h-6 w-full text-xs"
                  disabled={scale === 100}
                  onClick={() => setScale(100)}>
            {t('Reset to 100%')}
          </Button>
        </div>
      )}
    </div>
  )
}
