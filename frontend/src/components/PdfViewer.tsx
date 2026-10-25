// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import * as pdfjs from 'pdfjs-dist'
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?worker'
import {
  ChevronDown, ChevronUp, Copy, Maximize2, Minimize2, MessageSquarePlus, Search, X,
} from 'lucide-react'
import type { Annotation, AnnotationRect } from '../api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

pdfjs.GlobalWorkerOptions.workerPort = new PdfWorker()

// Annotation highlights are shared user data: this is a user-picked colour
// palette, so distinct hues are kept on purpose. Each value is a semi-
// transparent rgba painted over the PDF, so it stays legible on both the
// dark and light theme (the chrome around it uses tokens).
const COLORS: Record<string, string> = {
  yellow: 'rgba(250, 204, 21, 0.4)',
  green: 'rgba(34, 197, 94, 0.35)',
  pink: 'rgba(236, 72, 153, 0.35)',
  blue: 'rgba(59, 130, 246, 0.35)',
}

/** Copy to the clipboard. The async API only exists in a secure context
 * (https or localhost); an instance reached over plain http on the LAN falls
 * back to copying the live selection. */
function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => document.execCommand('copy'))
  } else {
    document.execCommand('copy')
  }
}

interface PageInfo { n: number; width: number; height: number; scale: number }

interface SearchMatch { page: number; rects: AnnotationRect[] }

const MAX_MATCHES = 500

interface Draft {
  page: number
  rects: AnnotationRect[]
  quote: string
  screenX: number
  screenY: number
}

export interface NewAnnotation {
  page: number
  rects: AnnotationRect[]
  quote: string
  note: string
  color: string
}

export default function PdfViewer({
  fileUrl, annotations, onCreate, onDelete,
}: {
  fileUrl: string
  annotations: Annotation[]
  onCreate: (a: NewAnnotation) => void
  onDelete: (id: number) => void
}) {
  const { t } = useTranslation()
  const scrollRef = useRef<HTMLDivElement>(null)
  const docRef = useRef<pdfjs.PDFDocumentProxy | null>(null)
  const canvasRefs = useRef<Record<number, HTMLCanvasElement | null>>({})
  const textRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const rendered = useRef<Set<number>>(new Set())
  // Bumped on every geometry change so stale (e.g. full-screen-scale) paints
  // still in flight cannot write their large dimensions back onto the canvas.
  const genRef = useRef(0)
  const tasksRef = useRef<Record<number, { cancel: () => void }>>({})
  const [numPages, setNumPages] = useState(0)
  const [fitWidth, setFitWidth] = useState(0)
  const [fullscreen, setFullscreen] = useState(false)
  const [pages, setPages] = useState<PageInfo[]>([])
  const [error, setError] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; draft: Draft } | null>(null)
  const [activeAnn, setActiveAnn] = useState<number | null>(null)

  // in-document search (ticket #14)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<SearchMatch[]>([])
  const [currentMatch, setCurrentMatch] = useState(0)
  // bumped each time a page's text layer finishes rendering, so a search
  // typed while the document is still loading picks up late pages
  const [layerVersion, setLayerVersion] = useState(0)
  const searchInputRef = useRef<HTMLInputElement>(null)

  const byPage = useMemo(() => {
    const map: Record<number, Annotation[]> = {}
    for (const a of annotations) (map[a.page] ??= []).push(a)
    return map
  }, [annotations])

  // Load the document (once per file).
  useEffect(() => {
    let cancelled = false
    rendered.current.clear()
    setPages([]); setNumPages(0); setError('')
    docRef.current = null
    const task = pdfjs.getDocument({ url: fileUrl, withCredentials: true })
    task.promise.then((doc) => {
      if (cancelled) return
      docRef.current = doc
      setNumPages(doc.numPages)
    }).catch((e) => { if (!cancelled) setError(String(e?.message || e)) })
    return () => { cancelled = true }
  }, [fileUrl])

  // Track the available width (fit-to-width), reacting to fullscreen + resizes.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    let r1 = 0, r2 = 0
    const apply = (force: boolean) => {
      const w = Math.max(el.clientWidth - 8, 200)
      setFitWidth((prev) => (force || Math.abs(prev - w) > 24 ? w : prev))
    }
    // force on mount + after layout settles (twice) so leaving full screen
    // always re-fits to the smaller box, whatever the reflow timing
    apply(true)
    r1 = requestAnimationFrame(() => { apply(true); r2 = requestAnimationFrame(() => apply(true)) })
    const ro = new ResizeObserver(() => apply(false))
    ro.observe(el)
    return () => { cancelAnimationFrame(r1); cancelAnimationFrame(r2); ro.disconnect() }
  }, [fullscreen])

  // Compute per-page geometry whenever the fit width changes (fullscreen/resize).
  useEffect(() => {
    const doc = docRef.current
    if (!doc || !numPages || !fitWidth) return
    let cancelled = false
    ;(async () => {
      const infos: PageInfo[] = []
      for (let n = 1; n <= numPages; n++) {
        const page = await doc.getPage(n)
        const base = page.getViewport({ scale: 1 })
        const scale = fitWidth / base.width
        const vp = page.getViewport({ scale })
        infos.push({ n, width: vp.width, height: vp.height, scale })
      }
      if (cancelled) return
      // invalidate any in-flight paints from the previous scale
      genRef.current += 1
      for (const t of Object.values(tasksRef.current)) { try { t.cancel() } catch { /* noop */ } }
      tasksRef.current = {}
      rendered.current.clear()
      setPages(infos)
    })()
    return () => { cancelled = true }
  }, [numPages, fitWidth])

  // Paint canvas + text layer once the page slots exist in the DOM.
  useEffect(() => {
    const doc = docRef.current
    if (!doc) return
    const gen = genRef.current
    for (const p of pages) {
      if (rendered.current.has(p.n)) continue
      const canvas = canvasRefs.current[p.n]
      const textDiv = textRefs.current[p.n]
      if (!canvas || !textDiv) continue
      rendered.current.add(p.n)
      doc.getPage(p.n).then(async (page) => {
        if (genRef.current !== gen) return  // a newer scale supersedes this paint
        const vp = page.getViewport({ scale: p.scale })
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        const dpr = window.devicePixelRatio || 1
        // buffer at device resolution; the DISPLAY size follows the page box via
        // CSS (w-full/h-full) so a stale paint can never enlarge the canvas
        canvas.width = Math.floor(vp.width * dpr)
        canvas.height = Math.floor(vp.height * dpr)
        ctx.scale(dpr, dpr)
        const task = page.render({ canvasContext: ctx, viewport: vp })
        tasksRef.current[p.n] = task
        await task.promise
        if (genRef.current !== gen) return
        textDiv.innerHTML = ''
        textDiv.style.setProperty('--scale-factor', String(p.scale))
        textDiv.style.setProperty('--total-scale-factor', String(p.scale))
        const tc = await page.getTextContent()
        if (genRef.current !== gen) return
        const layer = new pdfjs.TextLayer({
          textContentSource: tc, container: textDiv, viewport: vp })
        await layer.render()
        setLayerVersion((v) => v + 1)
      }).catch(() => rendered.current.delete(p.n))
    }
  }, [pages])

  // Find every occurrence in the rendered text layers: DOM Ranges give exact
  // client rects (even across spans), normalized to the page box so the
  // overlay survives zoom/fullscreen changes.
  useEffect(() => {
    const q = query.trim().toLowerCase()
    if (!q || !searchOpen) {
      setMatches([])
      setCurrentMatch(0)
      return
    }
    const timer = setTimeout(() => {
      const found: SearchMatch[] = []
      for (const p of pages) {
        if (found.length >= MAX_MATCHES) break
        const textDiv = textRefs.current[p.n]
        const pageEl = textDiv?.parentElement
        if (!textDiv || !pageEl) continue
        const walker = document.createTreeWalker(textDiv, NodeFilter.SHOW_TEXT)
        const nodes: Text[] = []
        const starts: number[] = []
        let full = ''
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          nodes.push(n as Text)
          starts.push(full.length)
          full += n.textContent ?? ''
        }
        const lower = full.toLowerCase()
        const box = pageEl.getBoundingClientRect()
        // char position -> (node, offset); end positions may sit at a node end
        const locate = (pos: number): [Text, number] => {
          let i = starts.length - 1
          while (i > 0 && starts[i] > pos) i--
          return [nodes[i], pos - starts[i]]
        }
        let idx = lower.indexOf(q)
        while (idx !== -1 && found.length < MAX_MATCHES) {
          const range = document.createRange()
          const [sn, so] = locate(idx)
          const [en, eo] = locate(idx + q.length - 1)
          range.setStart(sn, so)
          range.setEnd(en, eo + 1)
          const rects = Array.from(range.getClientRects())
            .filter((r) => r.width > 0.5 && r.height > 0.5)
            .map((r) => ({
              x: (r.left - box.left) / box.width,
              y: (r.top - box.top) / box.height,
              w: r.width / box.width,
              h: r.height / box.height,
            }))
          if (rects.length) found.push({ page: p.n, rects })
          idx = lower.indexOf(q, idx + q.length)
        }
      }
      setMatches(found)
      setCurrentMatch(0)
      if (found.length) scrollToMatch(found, 0)
    }, 250)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, searchOpen, pages, layerVersion])

  function scrollToMatch(all: SearchMatch[], index: number) {
    const m = all[index]
    const scroller = scrollRef.current
    const pageEl = textRefs.current[m?.page]?.parentElement
    if (!m || !scroller || !pageEl) return
    const pageTop = pageEl.getBoundingClientRect().top
      - scroller.getBoundingClientRect().top + scroller.scrollTop
    const y = pageTop + (m.rects[0]?.y ?? 0) * pageEl.offsetHeight
    scroller.scrollTo({ top: Math.max(0, y - scroller.clientHeight / 3),
                        behavior: 'smooth' })
  }

  const gotoMatch = (delta: number) => {
    if (!matches.length) return
    const next = (currentMatch + delta + matches.length) % matches.length
    setCurrentMatch(next)
    scrollToMatch(matches, next)
  }

  const openSearch = () => {
    setSearchOpen(true)
    setTimeout(() => searchInputRef.current?.select(), 0)
  }
  const closeSearch = () => {
    setSearchOpen(false)
    setMatches([])
  }

  // Ctrl/Cmd+F searches the PDF instead of the page while a viewer is mounted
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        openSearch()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // a click outside the selection menu, or Escape, dismisses it
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menu) return
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(null)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [menu])

  // per-page overlay data, with the global match index for the accent color
  const matchesByPage = useMemo(() => {
    const map: Record<number, { global: number; rects: AnnotationRect[] }[]> = {}
    matches.forEach((m, i) => {
      (map[m.page] ??= []).push({ global: i, rects: m.rects })
    })
    return map
  }, [matches])

  function selectionDraft(clientX: number, clientY: number): Draft | null {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null
    const range = sel.getRangeAt(0)
    let node: Node | null = range.startContainer
    let pageEl: HTMLElement | null = null
    while (node) {
      if (node instanceof HTMLElement && node.dataset.page) { pageEl = node; break }
      node = node.parentNode
    }
    if (!pageEl) return null
    const box = pageEl.getBoundingClientRect()
    const rects = Array.from(range.getClientRects())
      .filter((r) => r.width > 1 && r.height > 1)
      .map((r) => ({
        x: (r.left - box.left) / box.width,
        y: (r.top - box.top) / box.height,
        w: r.width / box.width,
        h: r.height / box.height,
      }))
    if (!rects.length) return null
    return { page: Number(pageEl.dataset.page), rects,
             quote: sel.toString().trim(), screenX: clientX, screenY: clientY }
  }

  // Right-click on a text selection -> our own context menu (copy / comment),
  // which replaces the native one and its "Copy" entry.
  function handleContextMenu(e: React.MouseEvent) {
    const d = selectionDraft(e.clientX, e.clientY)
    if (!d) return  // no selection: leave the native menu
    e.preventDefault()
    setActiveAnn(null)
    setDraft(null)
    setMenu({ x: e.clientX, y: e.clientY, draft: d })
  }

  return (
    <div className={fullscreen
           ? 'fixed inset-0 z-50 bg-background p-3 flex flex-col'
           : 'relative h-full min-w-0'}>
      <div className="absolute top-3 right-4 z-30 flex gap-1">
        {searchOpen ? (
          <div className="flex items-center gap-0.5 rounded-md border border-border bg-card/95 py-0.5 pl-2 pr-0.5 shadow-sm">
            <Search className="size-3.5 shrink-0 text-muted-foreground" />
            <input ref={searchInputRef} value={query} autoFocus
                   onChange={(e) => setQuery(e.target.value)}
                   onKeyDown={(e) => {
                     if (e.key === 'Enter') gotoMatch(e.shiftKey ? -1 : 1)
                     if (e.key === 'Escape') closeSearch()
                     e.stopPropagation()
                   }}
                   placeholder={t('Search in PDF…')}
                   className="h-6 w-36 bg-transparent px-1.5 text-xs text-foreground outline-none placeholder:text-muted-foreground" />
            <span className="min-w-10 px-0.5 text-right text-xs tabular-nums text-muted-foreground">
              {query.trim()
                ? matches.length
                  ? `${currentMatch + 1}/${matches.length}${matches.length >= MAX_MATCHES ? '+' : ''}`
                  : '0'
                : ''}
            </span>
            <Button variant="ghost" size="icon" className="size-6"
                    title={t('Previous match (Shift+Enter)')}
                    disabled={!matches.length} onClick={() => gotoMatch(-1)}>
              <ChevronUp className="size-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="size-6"
                    title={t('Next match (Enter)')}
                    disabled={!matches.length} onClick={() => gotoMatch(1)}>
              <ChevronDown className="size-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="size-6"
                    title={t('Close search (Esc)')} onClick={closeSearch}>
              <X className="size-3.5" />
            </Button>
          </div>
        ) : (
          <Button variant="outline" size="icon" className="size-7 bg-card/90 shadow-sm"
                  title={t('Search in the PDF (Ctrl+F)')} onClick={openSearch}>
            <Search className="size-3.5" />
          </Button>
        )}
        <Button variant="outline" size="icon" className="size-7 bg-card/90 shadow-sm"
                title={fullscreen ? t('Exit full screen') : t('Full screen')}
                onClick={() => setFullscreen((f) => !f)}>
          {fullscreen ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
        </Button>
      </div>
      <div ref={scrollRef} onContextMenu={handleContextMenu}
           className={cn('overflow-auto bg-muted rounded-lg p-1 min-w-0',
             fullscreen ? 'flex-1' : 'h-full w-full')}>
        {error && (
          <p className="text-sm text-destructive p-4">{t('Could not open the PDF:')} {error}</p>
        )}
        {!error && pages.length === 0 && (
          <p className="text-sm text-muted-foreground p-4">{t('Loading PDF…')}</p>
        )}
        {pages.map((p) => (
          <div key={p.n} data-page={p.n}
               className="relative mx-auto mb-2 bg-card shadow-sm"
               style={{ width: p.width, height: p.height }}>
            <canvas ref={(el) => { canvasRefs.current[p.n] = el }}
                    className="block w-full h-full" />
            <div ref={(el) => { textRefs.current[p.n] = el }}
                 className="textLayer" />
            {/* search-match highlights (between canvas and annotations) */}
            {matchesByPage[p.n] && (
              <div className="absolute inset-0" style={{ zIndex: 1, pointerEvents: 'none' }}>
                {matchesByPage[p.n].map((m) => m.rects.map((r, i) => (
                  <div key={`${m.global}-${i}`}
                       className="absolute rounded-[2px]"
                       style={{
                         left: `${r.x * 100}%`, top: `${r.y * 100}%`,
                         width: `${r.w * 100}%`, height: `${r.h * 100}%`,
                         background: m.global === currentMatch
                           ? 'rgba(249, 115, 22, 0.45)'   // current: orange
                           : 'rgba(250, 204, 21, 0.3)',   // others: yellow
                         outline: m.global === currentMatch
                           ? '1px solid rgba(249, 115, 22, 0.9)' : 'none',
                       }} />
                )))}
              </div>
            )}
            {/* annotation highlights (above the text layer). The container lets
                mouse events through so text stays selectable; only the boxes
                themselves are clickable. */}
            <div className="absolute inset-0" style={{ zIndex: 2, pointerEvents: 'none' }}>
              {(byPage[p.n] || []).map((a) => a.rects.map((r, i) => (
                <button type="button" key={`${a.id}-${i}`}
                     onClick={() => setActiveAnn(activeAnn === a.id ? null : a.id)}
                     aria-pressed={activeAnn === a.id}
                     aria-label={t('Highlight by {{author}}', { author: a.author })
                       + (a.note ? ': ' + a.note : '')}
                     title={`${a.author}${a.note ? ': ' + a.note : ''}`}
                     className="absolute cursor-pointer rounded-sm border-0 p-0"
                     style={{
                       left: `${r.x * 100}%`, top: `${r.y * 100}%`,
                       width: `${r.w * 100}%`, height: `${r.h * 100}%`,
                       background: COLORS[a.color] || COLORS.yellow,
                       pointerEvents: 'auto',
                       outline: activeAnn === a.id ? '1.5px solid var(--primary)' : 'none',
                     }} />
              )))}
            </div>
          </div>
        ))}
      </div>

      {/* note popover for a clicked highlight */}
      {activeAnn !== null && (() => {
        const a = annotations.find((x) => x.id === activeAnn)
        if (!a) return null
        return (
          <div className="absolute right-3 top-14 z-20 w-64 rounded-lg border border-border bg-popover p-3 shadow-lg text-sm text-popover-foreground">
            <p className="text-xs font-medium text-muted-foreground mb-1">{a.author}</p>
            {a.quote && (
              <p className="text-xs text-muted-foreground italic border-l-2 border-border pl-2 mb-1">
                “{a.quote.slice(0, 200)}”
              </p>
            )}
            {a.note && <p className="text-foreground">{a.note}</p>}
            <div className="flex justify-end gap-2 mt-2">
              {a.mine && (
                <Button variant="link" size="sm"
                        className="h-auto p-0 text-xs text-destructive hover:text-destructive"
                        onClick={() => { onDelete(a.id); setActiveAnn(null) }}>{t('Delete')}</Button>
              )}
              <Button variant="link" size="sm"
                      className="h-auto p-0 text-xs text-muted-foreground hover:text-muted-foreground"
                      onClick={() => setActiveAnn(null)}>{t('Close')}</Button>
            </div>
          </div>
        )
      })()}

      {menu && (
        <div ref={menuRef} role="presentation"
             className="fixed z-40 rounded-md border border-border bg-popover text-popover-foreground shadow-lg text-sm py-1"
             style={{ top: Math.min(menu.y, window.innerHeight - 90),
                      left: Math.min(menu.x, window.innerWidth - 200) }}
             // keep the text selection alive while the menu is clicked
             onMouseDown={(e) => e.preventDefault()}>
          <Button variant="ghost" size="sm"
                  className="h-auto w-full justify-start gap-2 rounded-none px-3 py-1.5 font-normal"
                  onClick={() => { copyText(menu.draft.quote); setMenu(null) }}>
            <Copy className="size-3.5" /> {t('Copy')}
          </Button>
          <Button variant="ghost" size="sm"
                  className="h-auto w-full justify-start gap-2 rounded-none px-3 py-1.5 font-normal"
                  onClick={() => { setDraft(menu.draft); setMenu(null) }}>
            <MessageSquarePlus className="size-3.5" /> {t('Add comment / highlight')}
          </Button>
        </div>
      )}

      {draft && (
        <DraftPopover draft={draft} onCancel={() => setDraft(null)}
          onSave={(note, color) => {
            onCreate({ page: draft.page, rects: draft.rects, quote: draft.quote,
                       note, color })
            setDraft(null)
            window.getSelection()?.removeAllRanges()
          }} />
      )}
    </div>
  )
}

function DraftPopover({ draft, onSave, onCancel }: {
  draft: Draft
  onSave: (note: string, color: string) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [note, setNote] = useState('')
  const [color, setColor] = useState('yellow')
  const top = Math.min(draft.screenY + 8, window.innerHeight - 190)
  const left = Math.min(draft.screenX, window.innerWidth - 260)
  return (
    <div role="presentation"
         className="fixed z-30 w-60 rounded-lg border border-border bg-popover p-3 shadow-xl text-sm text-popover-foreground"
         style={{ top, left }} onMouseUp={(e) => e.stopPropagation()}>
      <p className="text-xs font-medium text-muted-foreground mb-1">{t('New highlight')}</p>
      {draft.quote && (
        <p className="text-xs text-muted-foreground italic mb-2 max-h-16 overflow-auto">
          “{draft.quote.slice(0, 200)}”
        </p>
      )}
      <div className="flex gap-1 mb-2">
        {Object.keys(COLORS).map((c) => (
          <button type="button" key={c} onClick={() => setColor(c)}
                  aria-label={t('Color {{name}}', { name: c })} aria-pressed={color === c}
                  className={cn('h-5 w-5 rounded-full border',
                    color === c ? 'border-foreground' : 'border-transparent')}
                  style={{ background: COLORS[c] }} />
        ))}
      </div>
      <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                placeholder={t('Note (optional)…')}
                className="min-h-0 px-2 py-1.5 text-xs" />
      <div className="flex justify-end gap-2 mt-2">
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onCancel}>
          {t('Cancel')}
        </Button>
        <Button size="sm" className="h-7 px-2 text-xs" onClick={() => onSave(note, color)}>
          {t('Add highlight')}
        </Button>
      </div>
    </div>
  )
}
