// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

/** M4b — personal institutional access (EZproxy/OpenAthens/CAS).
 *
 * Credentials live in THIS browser only, per user:
 * - everything but passwords: localStorage["litubik.institutions.<userId>"]
 * - passwords: localStorage too when "remember on this device" is ticked,
 *   otherwise sessionStorage (gone when the tab closes).
 * They are sent to the backend only inside a retrieval request (ephemeral —
 * the server never stores them).
 */

export interface MyInstitution {
  name: string
  ezproxy_url: string
  scope: string
  username: string
  password: string
  remember_password: boolean
}

interface ProxyHit {
  name: string
  url: string
  country: string
}

const key = (userId: number) => `litubik.institutions.${userId}`

const blankInstitution = (): MyInstitution => ({
  name: '', ezproxy_url: '', scope: '', username: '', password: '',
  remember_password: false,
})

export function loadMyInstitutions(userId: number): MyInstitution[] {
  try {
    const saved: MyInstitution[] = JSON.parse(localStorage.getItem(key(userId)) ?? '[]')
    const session: Record<string, string> = JSON.parse(
      sessionStorage.getItem(key(userId)) ?? '{}')
    return saved.map((i) => ({
      ...i,
      password: i.remember_password ? (i.password ?? '') : (session[i.name] ?? ''),
    }))
  } catch {
    return []
  }
}

export function saveMyInstitutions(userId: number, list: MyInstitution[]) {
  const persisted = list.map((i) => ({
    ...i, password: i.remember_password ? i.password : '',
  }))
  localStorage.setItem(key(userId), JSON.stringify(persisted))
  const session: Record<string, string> = {}
  for (const i of list) {
    if (!i.remember_password && i.password) session[i.name] = i.password
  }
  sessionStorage.setItem(key(userId), JSON.stringify(session))
}

/** The entries usable for a retrieval run (proxy URL + password present). */
export function institutionsForRetrieve(userId: number) {
  return loadMyInstitutions(userId)
    .filter((i) => i.ezproxy_url && i.password)
    .map((i) => ({ name: i.name, ezproxy_url: i.ezproxy_url, scope: i.scope,
                   username: i.username, password: i.password }))
}

/** Institution-name input with typeahead against the bundled EZproxy database:
 * picking a hit fills the proxy URL automatically. Reused by the personal
 * access panel and the project's server-stored institutions form. */
export function InstitutionNameInput({ value, onPick, onChange, placeholder }: {
  value: string
  onChange: (name: string) => void
  onPick: (hit: ProxyHit) => void
  placeholder?: string
}) {
  const { t } = useTranslation()
  const [hits, setHits] = useState<ProxyHit[]>([])
  const [open, setOpen] = useState(false)
  // 'idle' while the query is too short; the others drive the dropdown so an
  // empty directory answer never looks like a dead field
  const [state, setState] = useState<'idle' | 'searching' | 'done' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')
  const timer = useRef<number>(undefined)
  const seq = useRef(0)

  const search = (q: string) => {
    window.clearTimeout(timer.current)
    const run = ++seq.current
    if (q.trim().length < 2) { setHits([]); setState('idle'); setOpen(false); return }
    setState('searching')
    setOpen(true)
    timer.current = window.setTimeout(async () => {
      try {
        const res = await api.get<ProxyHit[]>(
          `/api/institution-proxies?q=${encodeURIComponent(q)}`)
        if (run !== seq.current) return  // a later keystroke already answered
        setHits(res)
        setState('done')
      } catch (e) {
        if (run !== seq.current) return
        setHits([])
        // a 503 carries the real cause (directory absent from the install)
        setErrorMsg(e instanceof ApiError ? e.message : '')
        setState('error')
      }
    }, 250)
  }
  useEffect(() => () => window.clearTimeout(timer.current), [])

  return (
    <div className="relative flex-1">
      <Input
        value={value}
        placeholder={placeholder ?? t('Institution name (type to search the proxy directory)')}
        onChange={(e) => { onChange(e.target.value); search(e.target.value) }}
        onBlur={() => window.setTimeout(() => setOpen(false), 200)}
        onFocus={() => state !== 'idle' && setOpen(true)}
      />
      {open && state !== 'idle' && (
        <ul className="absolute z-20 mt-1 max-h-52 w-full overflow-y-auto rounded-md border border-border bg-background p-1 shadow-lg">
          {hits.map((h) => (
            <li key={`${h.name}|${h.url}`}>
              <button
                type="button"
                className="w-full rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => { onPick(h); setOpen(false) }}
              >
                <span className="text-foreground">{h.name}</span>
                {h.country && <span className="text-muted-foreground"> · {h.country}</span>}
              </button>
            </li>
          ))}
          {state === 'searching' && (
            <li className="px-2 py-1.5 text-xs text-muted-foreground">{t('Searching…')}</li>
          )}
          {state === 'done' && hits.length === 0 && (
            <li className="px-2 py-1.5 text-xs text-muted-foreground">
              {t('No institution found in the proxy directory — keep your own name and paste the proxy login URL below (your library can give it to you).')}
            </li>
          )}
          {state === 'error' && (
            <li className="px-2 py-1.5 text-xs text-destructive">
              {errorMsg || t('The proxy directory could not be reached — you can still fill the URL by hand.')}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

/** A server-stored institution (project-level or app-wide). Passwords are
 * write-only: the API only says whether one is stored. */
export interface ServerInstitution {
  name: string
  ezproxy_url: string
  username: string
  scope: string
  auth_type: string
  has_password: boolean
  password?: string  // filled only while typing a new one
}

/** Read-only list of server-stored institutions, for the places that show
 * what is already configured without offering to edit it. */
export function InstitutionList({ items, empty }: {
  items: ServerInstitution[]
  empty: string
}) {
  if (items.length === 0) {
    return <p className="text-xs text-muted-foreground">{empty}</p>
  }
  return (
    <ul className="space-y-1">
      {items.map((inst, i) => (
        <li key={i} className="flex items-center gap-2 text-xs">
          <span className="rounded border border-border px-1.5 py-0.5 text-foreground">
            🔒 {inst.name}
          </span>
          <span className="truncate text-muted-foreground">{inst.ezproxy_url}</span>
          {inst.username && (
            <span className="text-muted-foreground/70">· {inst.username}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Editor for server-stored institutions — shared by the project's full-text
 * settings and the app-wide institutions page. The caller owns the list and
 * the saving; this only renders the rows. */
export function ServerInstitutionsEditor({ items, onChange }: {
  items: ServerInstitution[]
  onChange: (items: ServerInstitution[]) => void
}) {
  const { t } = useTranslation()
  const update = (i: number, patch: Partial<ServerInstitution>) =>
    onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  return (
    <div>
      {items.map((inst, i) => (
        <div key={i} className="mb-2 space-y-2 rounded-lg border border-border p-3">
          <div className="flex gap-2">
            <InstitutionNameInput
              value={inst.name}
              onChange={(name) => update(i, { name })}
              onPick={(h) => update(i, { name: h.name, ezproxy_url: h.url })}
            />
            <Button variant="ghost" size="icon"
                    className="text-muted-foreground hover:text-destructive"
                    title={t('Remove this institution')}
                    onClick={() => onChange(items.filter((_, j) => j !== i))}>✕</Button>
          </div>
          <Input value={inst.ezproxy_url}
                 placeholder={t('EZProxy/CAS login URL (…/login?url=$@)')}
                 onChange={(e) => update(i, { ezproxy_url: e.target.value })} />
          <div className="flex gap-2">
            <Input value={inst.username} placeholder={t('Username')}
                   onChange={(e) => update(i, { username: e.target.value })}
                   className="flex-1" />
            <Input type="password"
                   placeholder={inst.has_password ? t('Password (stored)') : t('Password')}
                   value={inst.password ?? ''}
                   onChange={(e) => update(i, { password: e.target.value })}
                   className="flex-1" />
            <Input value={inst.scope} placeholder={t('CAS scope')}
                   onChange={(e) => update(i, { scope: e.target.value })}
                   className="w-24" />
          </div>
        </div>
      ))}
      <Button variant="outline" size="sm"
              onClick={() => onChange([...items, {
                name: '', ezproxy_url: '', username: '', scope: '',
                auth_type: '', has_password: false, password: '' }])}>
        {t('+ Add institution')}
      </Button>
    </div>
  )
}

/** Editor for the user's own institutional access. Rendered wherever a member
 * may launch retrieval (Full-text page) and in the project setup wizard. */
export function MyInstitutionsPanel({ userId, onChanged }: {
  userId: number
  onChanged?: () => void
}) {
  const { t } = useTranslation()
  // one blank row when nothing is stored yet: the institution search must be
  // visible without hunting for an "add" button first
  const withBlank = (l: MyInstitution[]) => (l.length > 0 ? l : [blankInstitution()])
  const [list, setList] = useState<MyInstitution[]>(
    () => withBlank(loadMyInstitutions(userId)))
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setList(withBlank(loadMyInstitutions(userId)))
    setSaved(false)
  }, [userId])  // eslint-disable-line react-hooks/exhaustive-deps

  const update = (i: number, patch: Partial<MyInstitution>) =>
    setList((l) => l.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  const persist = () => {
    const filled = list.filter((i) => i.name.trim() || i.ezproxy_url.trim())
    saveMyInstitutions(userId, filled)
    setList(withBlank(filled))
    setSaved(true)
    onChanged?.()
    window.setTimeout(() => setSaved(false), 2500)
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {t('Your personal library access (EZproxy, OpenAthens, CAS…). Stored only in this browser — never on the server: credentials are sent once per retrieval run and forgotten.')}
      </p>
      {list.map((inst, i) => (
        <div key={i} className="space-y-2 rounded-lg border border-border p-3">
          <div className="flex gap-2">
            <InstitutionNameInput
              value={inst.name}
              onChange={(name) => update(i, { name })}
              onPick={(h) => update(i, { name: h.name, ezproxy_url: h.url })}
            />
            <Button variant="ghost" size="icon"
                    className="text-muted-foreground hover:text-destructive"
                    title={t('Remove this institution')}
                    onClick={() => setList((l) => withBlank(l.filter((_, j) => j !== i)))}>
              ✕
            </Button>
          </div>
          <Input value={inst.ezproxy_url}
                 placeholder={t('Proxy login URL (…/login?url=$@) — filled from the directory')}
                 onChange={(e) => update(i, { ezproxy_url: e.target.value })} />
          <div className="flex gap-2">
            <Input value={inst.username} placeholder={t('Username')}
                   autoComplete="off"
                   onChange={(e) => update(i, { username: e.target.value })}
                   className="flex-1" />
            <Input type="password" value={inst.password} placeholder={t('Password')}
                   autoComplete="new-password"
                   onChange={(e) => update(i, { password: e.target.value })}
                   className="flex-1" />
            <Input value={inst.scope} placeholder={t('CAS scope')}
                   title={t('Only for federated CAS portals that ask to pick an establishment')}
                   onChange={(e) => update(i, { scope: e.target.value })}
                   className="w-24" />
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" checked={inst.remember_password}
                   onChange={(e) => update(i, { remember_password: e.target.checked })} />
            {t('Remember the password on this device (stored unencrypted in this browser); unticked, it is kept until this tab closes.')}
          </label>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm"
                onClick={() => setList((l) => [...l, blankInstitution()])}>
          {t('+ Add another institution')}
        </Button>
        {list.length > 0 && (
          <Button size="sm" onClick={persist}>{t('Save in this browser')}</Button>
        )}
        {saved && <span className="text-xs text-success">{t('✓ Saved locally')}</span>}
      </div>
    </div>
  )
}
