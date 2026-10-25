// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Languages } from 'lucide-react'
import { api, ApiError } from '@/api'
import { Badge } from './ui/badge'

/** AI translation of a record's title + abstract into the interface language —
 * a reading aid. The original stays one click away and is what gets edited,
 * highlighted for search terms in the equation's language, and screened. The
 * server caches one translation per language for the whole team. */
export interface TranslationEntry {
  same_language: boolean
  source_language: string
  title: string
  abstract: string
  provider: string
  model: string
  at: string
}
export type Translations = Record<string, TranslationEntry>

// Per-viewer preference: translate by myself whatever I open. Browser-held —
// it is a reading habit, not project state.
const AUTO_KEY = 'litubik.autoTranslate'
const listeners = new Set<() => void>()
const readAuto = () => {
  try { return localStorage.getItem(AUTO_KEY) === '1' } catch { return false }
}
const writeAuto = (on: boolean) => {
  try { localStorage.setItem(AUTO_KEY, on ? '1' : '0') } catch { /* private mode */ }
  listeners.forEach((notify) => notify())
}
const subscribe = (notify: () => void) => {
  listeners.add(notify)
  return () => { listeners.delete(notify) }
}

// Requests in flight, shared by every caller: a record that becomes current
// while its prefetch is still running joins that request instead of paying
// for a second translation. Nothing is kept once it settles — the server
// cache and the queue payload are the source of truth.
const inflight = new Map<string, Promise<TranslationEntry>>()
function fetchTranslation(projectId: number, id: number, lang: string) {
  const key = `${projectId}:${id}:${lang}`
  let pending = inflight.get(key)
  if (!pending) {
    pending = api.post<TranslationEntry>(
      `/api/projects/${projectId}/records/${id}/translate`, { lang })
      .finally(() => inflight.delete(key))
    inflight.set(key, pending)
  }
  return pending
}

/** Automatic mode only: translate the next few records of the queue ahead of
 * the reviewer, so the text is already there when they reach them. */
export function usePrefetchTranslations(projectId: number,
  upcoming: { id: number; translations?: Translations }[]) {
  const { i18n } = useTranslation()
  const lang = i18n.language === 'fr' ? 'fr' : 'en'
  const auto = useSyncExternalStore(subscribe, readAuto)
  const asked = useRef(new Set<string>())
  const ids = upcoming.map((r) => r.id).join(',')
  useEffect(() => {
    if (!auto) return
    for (const item of upcoming) {
      const key = `${item.id}:${lang}`
      if (item.translations?.[lang] || asked.current.has(key)) continue
      asked.current.add(key)
      // best effort: a failure shows up when the record is actually opened
      fetchTranslation(projectId, item.id, lang).catch(() => {})
    }
  }, [auto, lang, ids, projectId])  // eslint-disable-line
}

interface LocalState {
  id: number
  lang: string
  entry?: TranslationEntry
  show?: boolean
  error?: string
}

export function useRecordTranslation({ projectId, recordId, translations, autoAllowed = true }: {
  projectId: number
  recordId: number
  translations?: Translations
  /** false where opening many records at once would fire many AI calls */
  autoAllowed?: boolean
}) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language === 'fr' ? 'fr' : 'en'
  const auto = useSyncExternalStore(subscribe, readAuto)

  // one hook instance outlives the records it shows (the screening card):
  // local state is only valid for the record + language it was made for
  const [local, setLocal] = useState<LocalState>({ id: recordId, lang })
  const state = local.id === recordId && local.lang === lang
    ? local : { id: recordId, lang }
  const current = useRef({ id: recordId, lang })
  current.current = { id: recordId, lang }

  const entry = state.entry ?? translations?.[lang]
  const show = state.show ?? auto

  const request = useMutation({
    mutationFn: (vars: { id: number; lang: string }) =>
      fetchTranslation(projectId, vars.id, vars.lang),
    onSuccess: (data, vars) => {
      if (vars.id !== current.current.id || vars.lang !== current.current.lang) return
      setLocal({ ...vars, entry: data, show: true })
    },
    onError: (e, vars) => {
      if (vars.id !== current.current.id || vars.lang !== current.current.lang) return
      setLocal({ ...vars, show: false,
        error: e instanceof ApiError ? e.message : t('Translation failed') })
    },
  })

  // auto mode: ask once per record + language, never in a loop after a failure
  const asked = useRef(new Set<string>())
  useEffect(() => {
    const key = `${recordId}:${lang}`
    if (!auto || !autoAllowed || entry || asked.current.has(key)) return
    asked.current.add(key)
    request.mutate({ id: recordId, lang })
  }, [auto, autoAllowed, entry, recordId, lang])  // eslint-disable-line

  const pending = request.isPending
    && request.variables?.id === recordId && request.variables?.lang === lang

  return {
    /** the translation to display instead of the original, if any */
    shown: show && entry && !entry.same_language ? entry : null,
    control: {
      lang, entry, show, pending, auto, error: state.error,
      translate: () => request.mutate({ id: recordId, lang }),
      setShow: (next: boolean) => setLocal({ ...state, show: next }),
      setAuto: writeAuto,
    },
  }
}

type Control = ReturnType<typeof useRecordTranslation>['control']

export function TranslateControl({ control, className, withAuto = true }: {
  control: Control
  className?: string
  withAuto?: boolean
}) {
  const { t } = useTranslation()
  const { lang, entry, show, pending, auto, error } = control
  const language = lang === 'fr' ? t('French') : t('English')
  const linkClass = 'inline-flex items-center gap-1 text-primary hover:underline disabled:opacity-60'

  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground ${className ?? ''}`}>
      {entry?.same_language ? (
        <span>{t('Already in {{language}}', { language })}</span>
      ) : entry ? (
        <>
          <button type="button" className={linkClass} onClick={() => control.setShow(!show)}>
            <Languages className="size-3.5" />
            {show ? t('Show original') : t('Show the translation')}
          </button>
          {show && (
            <Badge variant="outline"
                   title={t('Machine translation, provided as a reading aid. The original text remains the reference — check it before deciding.')}>
              {t('AI translation · {{model}}', { model: entry.model || entry.provider })}
            </Badge>
          )}
        </>
      ) : (
        <button type="button" className={linkClass} disabled={pending}
                onClick={control.translate}>
          <Languages className="size-3.5" />
          {pending ? t('Translating…') : t('Translate to {{language}}', { language })}
        </button>
      )}
      {withAuto && (
        <label className="inline-flex cursor-pointer items-center gap-1"
               title={t('Translate every abstract I open that is not in my language. Uses the project’s AI key; each text is translated once for the whole team.')}>
          <input type="checkbox" className="size-3 accent-primary" checked={auto}
                 onChange={(e) => control.setAuto(e.target.checked)} />
          {t('Translate automatically')}
        </label>
      )}
      {error && <span className="text-destructive">{error}</span>}
    </div>
  )
}
