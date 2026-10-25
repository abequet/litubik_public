// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError,
  type CustomDatabase, type DatabaseKey, type IdLabel, type ProjectDatabase,
  type User,
} from '../api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

/** App-wide database keys (Administration). Project-scoped keys reuse
 * DatabaseKeyGrid from Project settings (M4b). */
export default function DatabaseSettings() {
  const { t } = useTranslation()
  const { data: me } = useQuery<User | null>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const isAppAdmin = !!me?.is_admin

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">{t('Database API keys')}</h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Add a Scopus (Elsevier) or IEEE Xplore API key to turn those closed databases into automatic sources: result counts on the Equations page and paginated search on the Search page run through the API instead of the assisted-manual export. Keys are stored encrypted and app-wide.')}
        {!isAppAdmin && ' ' + t('Only an application admin can change them.')}
      </p>
      <DatabaseKeyGrid projectId={null} editable={isAppAdmin} />
    </div>
  )
}

/** Key cards for one scope: global (projectId null) or one project (M4b —
 * managed by that project's admins, overriding the global key). */
export function DatabaseKeyGrid({ projectId, editable }: {
  projectId: number | null
  editable: boolean
}) {
  const suffix = projectId != null ? `?project_id=${projectId}` : ''
  const { data: keys = [] } = useQuery<DatabaseKey[]>({
    queryKey: ['database-keys', projectId],
    queryFn: () => api.get(`/api/database-credentials${suffix}`),
  })
  return (
    <div className="grid max-w-2xl gap-4">
      {keys.map((k) => (
        <KeyCard key={k.provider} entry={k} projectId={projectId} editable={editable} />
      ))}
    </div>
  )
}

/** Every database available to a project: the two that take an API key, the
 * free automatic ones, the assisted-manual ones (Web of Science, EBSCO…) and
 * the databases the team added itself. Used by the project settings tab and
 * by step 2/3 of the setup wizard. */
export function ProjectDatabasesPanel({ projectId, editable }: {
  projectId: number
  editable: boolean
}) {
  const { t } = useTranslation()
  const { data: databases = [] } = useQuery<ProjectDatabase[]>({
    queryKey: ['project-databases', projectId],
    queryFn: () => api.get(`/api/database-credentials/databases?project_id=${projectId}&all=true`),
  })
  return (
    <div className="max-w-2xl space-y-6">
      <SearchedDatabasesSection projectId={projectId} databases={databases}
                                editable={editable} />
      <section>
        <h3 className="mb-2 text-sm font-medium text-foreground">
          {t('Databases that accept an API key')}
        </h3>
        <DatabaseKeyGrid projectId={projectId} editable={editable} />
      </section>

      <section>
        <h3 className="mb-1 text-sm font-medium text-foreground">
          {t('Other databases already available')}
        </h3>
        <p className="mb-2 text-xs text-muted-foreground">
          {t('These need no key here: the free ones are searched automatically, the others (Web of Science, EBSCO/PsycINFO, ACM…) work in assisted-manual mode — the app writes the query in their syntax, you export from the database and import the file on the Search page.')}
        </p>
        <ul className="flex flex-wrap gap-2">
          {databases.filter((d) => d.mode !== 'api_key' && !d.custom).map((d) => (
            <li key={d.id}>
              <Badge variant={d.mode === 'api' ? 'default' : 'outline'}>
                {d.label}{d.mode === 'api' ? ` · ${t('automatic')}` : ` · ${t('assisted manual')}`}
              </Badge>
            </li>
          ))}
        </ul>
      </section>

      <CustomDatabasesSection projectId={projectId} editable={editable} />
    </div>
  )
}

/** Which databases this review searches: the Equations and Search pages show
 * only these, the counts and the AI drafts of a typed equation cover only
 * these, PRISMA-S reports these. Nothing selected = every database. */
function SearchedDatabasesSection({ projectId, databases, editable }: {
  projectId: number
  databases: ProjectDatabase[]
  editable: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const builtin = databases.filter((d) => !d.custom)
  const allSelected = builtin.every((d) => d.selected)
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['project-databases', projectId] })
    queryClient.invalidateQueries({ queryKey: ['databases', projectId] })
    queryClient.invalidateQueries({ queryKey: ['equations', projectId] })
    queryClient.invalidateQueries({ queryKey: ['projects'] })
  }
  const save = useMutation({
    mutationFn: (ids: string[] | null) =>
      api.put(`/api/projects/${projectId}`, { databases: ids }),
    onSuccess: () => { setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const toggle = (id: string, on: boolean) => {
    const current = builtin.filter((d) => d.selected).map((d) => d.id)
    const next = on ? [...current, id] : current.filter((x) => x !== id)
    save.mutate(next.length === builtin.length ? null : next)
  }
  return (
    <section>
      <h3 className="mb-1 text-sm font-medium text-foreground">
        {t('Databases searched by this review')}
      </h3>
      <p className="mb-2 text-xs text-muted-foreground">
        {t('Tick the databases your protocol names. Only these appear on the Equations and Search pages, get counts and AI-drafted syntaxes, and are reported in PRISMA-S. Databases you add yourself always count.')}
      </p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {builtin.map((d) => (
          <li key={d.id}>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input type="checkbox" checked={d.selected} disabled={!editable || save.isPending}
                     onChange={(e) => toggle(d.id, e.target.checked)}
                     className="accent-primary" />
              {d.label}
            </label>
          </li>
        ))}
      </ul>
      {editable && !allSelected && (
        <Button variant="link" size="sm" className="mt-1 h-auto p-0 text-xs"
                onClick={() => save.mutate(null)} disabled={save.isPending}>
          {t('Search every database')}
        </Button>
      )}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </section>
  )
}

/** Databases the project declares itself — a national portal, a publisher
 * platform, grey literature… always assisted-manual. */
function CustomDatabasesSection({ projectId, editable }: {
  projectId: number
  editable: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const { data: customs = [] } = useQuery<CustomDatabase[]>({
    queryKey: ['custom-databases', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/custom-databases`),
  })
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['custom-databases', projectId] })
    queryClient.invalidateQueries({ queryKey: ['project-databases', projectId] })
    queryClient.invalidateQueries({ queryKey: ['databases', projectId] })
    queryClient.invalidateQueries({ queryKey: ['equations', projectId] })
  }

  return (
    <section>
      <h3 className="mb-1 text-sm font-medium text-foreground">
        {t('Databases added by this project')}
      </h3>
      <p className="mb-2 text-xs text-muted-foreground">
        {t('Missing a source? Add it here and it appears on the Equations and Search pages like the built-in ones: the app writes the query in the syntax you pick, you export from the database and import the file — the records count in PRISMA.')}
      </p>
      <div className="space-y-3">
        {customs.map((c) => (
          <CustomDatabaseCard key={c.id} projectId={projectId} entry={c}
                              editable={editable} onChanged={invalidate} />
        ))}
        {customs.length === 0 && !adding && (
          <p className="text-xs text-muted-foreground">{t('No database added yet.')}</p>
        )}
        {adding && (
          <CustomDatabaseForm projectId={projectId} entry={null}
                              onDone={() => { setAdding(false); invalidate() }}
                              onCancel={() => setAdding(false)} />
        )}
        {editable && !adding && (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            {t('+ Add a database')}
          </Button>
        )}
      </div>
    </section>
  )
}

function CustomDatabaseCard({ projectId, entry, editable, onChanged }: {
  projectId: number
  entry: CustomDatabase
  editable: boolean
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')
  const remove = useMutation({
    mutationFn: () => api.del(
      `/api/projects/${projectId}/custom-databases/${entry.id}`),
    onSuccess: () => { setError(''); onChanged() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Remove failed')),
  })

  if (editing) {
    return (
      <CustomDatabaseForm projectId={projectId} entry={entry}
                          onDone={() => { setEditing(false); onChanged() }}
                          onCancel={() => setEditing(false)} />
    )
  }
  return (
    <Card className="p-3">
      <div className="flex items-center gap-2">
        <span className="flex-1 text-sm font-medium text-foreground">{entry.label}</span>
        <Badge variant="outline">{t('assisted manual')}</Badge>
        {editable && (
          <>
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
              {t('Edit')}
            </Button>
            <Button variant="ghost" size="sm"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => remove.mutate()} disabled={remove.isPending}>
              {t('Remove')}
            </Button>
          </>
        )}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {t('Imports are traced under “{{source}}”.', { source: entry.db_id })}
        {entry.n_imports > 0 && ' ' + t('{{count}} import(s) so far — removing the database keeps them.', { count: entry.n_imports })}
      </p>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </Card>
  )
}

function CustomDatabaseForm({ projectId, entry, onDone, onCancel }: {
  projectId: number
  entry: CustomDatabase | null
  onDone: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [label, setLabel] = useState(entry?.label ?? '')
  const [syntax, setSyntax] = useState(entry?.syntax ?? 'generic')
  const [url, setUrl] = useState(entry?.url ?? '')
  const [instructions, setInstructions] = useState(entry?.instructions ?? '')
  const [error, setError] = useState('')
  const { data: syntaxes } = useQuery<{ syntaxes: IdLabel[] }>({
    queryKey: ['database-syntaxes', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/custom-databases/syntaxes`),
  })
  const save = useMutation({
    mutationFn: () => {
      const body = { label: label.trim(), syntax, url: url.trim(), instructions }
      return entry
        ? api.put(`/api/projects/${projectId}/custom-databases/${entry.id}`, body)
        : api.post(`/api/projects/${projectId}/custom-databases`, body)
    },
    onSuccess: () => { setError(''); onDone() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  return (
    <Card className="space-y-2 p-3">
      <Input value={label} onChange={(e) => setLabel(e.target.value)}
             placeholder={t('Database name (e.g. Cairn.info, TRID, ERIC)')} />
      <div className="flex items-center gap-2">
        <label className="text-xs text-muted-foreground">{t('Query syntax:')}</label>
        <Select value={syntax} onValueChange={setSyntax}>
          <SelectTrigger className="h-8 w-auto min-w-56 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(syntaxes?.syntaxes ?? []).map((s) => (
              <SelectItem key={s.id} value={s.id}>{s.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <p className="text-xs text-muted-foreground">
        {t('The app cannot know this database’s query language — pick the closest one, or the generic boolean string, and adjust the query by hand on the Equations page if needed.')}
      </p>
      <Input value={url} onChange={(e) => setUrl(e.target.value)}
             placeholder={t('Link to the database (optional, https://…)')} />
      <Textarea value={instructions} rows={3}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder={t('Search and export instructions for your co-reviewers (optional)')} />
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => save.mutate()}
                disabled={label.trim().length < 2 || save.isPending}>
          {entry ? t('Save') : t('Add the database')}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>{t('Cancel')}</Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </Card>
  )
}

function KeyCard({ entry, projectId, editable }: {
  entry: DatabaseKey
  projectId: number | null
  editable: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [value, setValue] = useState('')
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const suffix = projectId != null ? `?project_id=${projectId}` : ''
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['database-keys'] })
    // equation database method (api/manual) depends on the key
    queryClient.invalidateQueries({ queryKey: ['databases'] })
  }
  const save = useMutation({
    mutationFn: () => api.put('/api/database-credentials',
      { provider: entry.provider, api_key: value.trim(), project_id: projectId }),
    onSuccess: () => { setValue(''); setMsg(t('Key saved.')); setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const remove = useMutation({
    mutationFn: () => api.del(`/api/database-credentials/${entry.provider}${suffix}`),
    onSuccess: () => { setMsg(''); setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Remove failed')),
  })
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; detail: string }>(
      `/api/database-credentials/${entry.provider}/test${suffix}`),
    onSuccess: (r) => { setMsg(r.detail); setError(r.ok ? '' : r.detail) },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Test failed')),
  })

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-foreground">{entry.label}</h2>
        <span className="flex items-center gap-2">
          {projectId != null && !entry.configured && entry.global_configured && (
            <Badge variant="default" title={t('The app-wide key applies to this project until you store a project key here')}>
              {t('app-wide key active')}
            </Badge>
          )}
          <Badge variant={entry.configured ? 'success' : 'outline'}>
            {entry.configured ? t('configured') : t('not set')}
          </Badge>
        </span>
      </div>
      {entry.help_url && editable && (
        <p className="mt-1 text-xs text-muted-foreground">
          {t('No key yet? It usually comes with your institution’s subscription — request one at')}{' '}
          <a href={entry.help_url} target="_blank" rel="noreferrer"
             className="text-primary hover:underline">{entry.help_url}</a>.{' '}
          {t('Without a key, this database stays available in assisted-manual mode (translated query + export file import).')}
        </p>
      )}
      {editable ? (
        <>
          <div className="mt-3 flex gap-2">
            <Input
              type="password" value={value} placeholder={entry.configured
                ? t('Enter a new key to replace the stored one') : t('Paste the API key')}
              onChange={(e) => setValue(e.target.value)}
              className="flex-1" />
            <Button onClick={() => save.mutate()} disabled={!value.trim() || save.isPending}>
              {t('Save')}
            </Button>
          </div>
          {entry.configured && (
            <div className="mt-2 flex gap-2">
              <Button variant="outline" size="sm"
                      onClick={() => test.mutate()} disabled={test.isPending}>
                {test.isPending ? t('Testing…') : t('Test key')}
              </Button>
              <Button variant="outline" size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => remove.mutate()} disabled={remove.isPending}>
                {t('Remove')}
              </Button>
            </div>
          )}
        </>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          {entry.configured ? t('A key is configured.') : t('No key configured.')}
        </p>
      )}
      {msg && !error && <p className="mt-2 text-sm text-success">{msg}</p>}
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
    </Card>
  )
}
