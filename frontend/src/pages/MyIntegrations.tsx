// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, type ZoteroLibrary, type ZoteroProbe, type ZoteroStatus,
} from '../api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import LiveStatus from '../components/LiveStatus'

/** Personal integrations (roadmap chantier 4). Today: Zotero. The API key
 * belongs to the account (stored encrypted on the server, never shared
 * through sync) and opens the user's own library or one of their groups —
 * the Search page pulls collections from it, the export dialog pushes
 * references into it. */
export default function MyIntegrationsPage() {
  const { t } = useTranslation()
  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('My integrations')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Connect your reference manager to import a collection into a project and send references back to it. Keys are personal: they are stored encrypted on this server, used only for your own actions, and never shared with other members or instances.')}
      </p>
      <ZoteroCard />
      <p className="mt-4 max-w-2xl text-xs text-muted-foreground">
        {t('Mendeley is not supported: its API requires an OAuth application registration and is being phased out. Export RIS or BibTeX instead and import the file there.')}
      </p>
    </div>
  )
}

function ZoteroCard() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: status } = useQuery<ZoteroStatus>({
    queryKey: ['zotero-status'], queryFn: () => api.get('/api/integrations/zotero'),
  })
  const [key, setKey] = useState('')
  const [probe, setProbe] = useState<ZoteroProbe | null>(null)
  const [choice, setChoice] = useState<ZoteroLibrary | null>(null)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['zotero-status'] })
    queryClient.invalidateQueries({ queryKey: ['zotero-collections'] })
  }
  const check = useMutation({
    mutationFn: () => api.post<ZoteroProbe>('/api/integrations/zotero/probe',
      { api_key: key.trim() || null }),
    onSuccess: (r) => {
      setProbe(r); setError(''); setMsg('')
      const current = r.libraries.find((l) =>
        status?.configured && l.type === status.library_type && l.id === status.library_id)
      setChoice(current ?? r.libraries[0] ?? null)
    },
    onError: (e) => { setProbe(null); setError(e instanceof ApiError ? e.message : t('Check failed')) },
  })
  const save = useMutation({
    mutationFn: () => api.put<ZoteroStatus>('/api/integrations/zotero', {
      api_key: key.trim() || null,
      library_type: choice?.type, library_id: choice?.id,
    }),
    onSuccess: () => {
      setKey(''); setProbe(null); setError('')
      setMsg(t('Zotero library saved.')); invalidate()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const remove = useMutation({
    mutationFn: () => api.del('/api/integrations/zotero'),
    onSuccess: () => { setMsg(''); setError(''); setProbe(null); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Remove failed')),
  })

  const configured = !!status?.configured
  return (
    <Card className="max-w-2xl p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-foreground">Zotero</h2>
        <Badge variant={configured ? 'success' : 'outline'}>
          {configured ? t('connected') : t('not connected')}
        </Badge>
      </div>
      {configured && status && (
        <p className="mt-1 text-sm text-muted-foreground">
          {t('Connected as {{username}} — library: {{library}}', {
            username: status.username ?? '?',
            library: status.library_type === 'user' ? t('My library') : (status.library_name ?? '?') })}
          {' '}
          {status.write
            ? <span>{t('(read and write)')}</span>
            : <span className="text-warning">{t('(read only — exports to Zotero need a key with write access)')}</span>}
        </p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        {t('Create a key on')}{' '}
        <a href={status?.key_url ?? 'https://www.zotero.org/settings/keys/new'}
           target="_blank" rel="noreferrer" className="text-primary hover:underline">
          zotero.org/settings/keys
        </a>{' '}
        {t('with “Allow library access” and, to send references from LitUbik, “Allow write access” (plus the group you want, if any). Then paste it here and pick the library.')}
      </p>
      <div className="mt-3 flex gap-2">
        <Input
          type="password" value={key} aria-label={t('Zotero API key')}
          placeholder={configured ? t('Enter a new key to replace the stored one')
                                  : t('Paste the API key')}
          onChange={(e) => setKey(e.target.value)}
          className="flex-1" />
        <Button variant={configured && !key.trim() ? 'outline' : 'default'}
                onClick={() => check.mutate()}
                disabled={(!configured && !key.trim()) || check.isPending}>
          {check.isPending ? t('Checking…') : t('Check key')}
        </Button>
      </div>
      {probe && (
        <fieldset className="mt-3 rounded-md border p-3">
          <legend className="px-1 text-xs font-medium text-muted-foreground">
            {t('Key of {{username}} — choose the library to use', { username: probe.username })}
          </legend>
          {probe.libraries.length === 0 && (
            <p className="text-sm text-destructive">
              {t('This key opens no library: re-create it with “Allow library access”.')}
            </p>
          )}
          <ul className="space-y-1">
            {probe.libraries.map((lib) => (
              <li key={`${lib.type}-${lib.id}`}>
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" name="zotero-library"
                         checked={choice?.type === lib.type && choice?.id === lib.id}
                         onChange={() => setChoice(lib)} />
                  <span>{lib.type === 'user' ? t('My library') : lib.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {lib.type === 'group' ? t('(group)') : ''}{' '}
                    {lib.write ? t('read/write') : t('read only')}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <Button className="mt-2" size="sm" onClick={() => save.mutate()}
                  disabled={!choice || save.isPending}>
            {save.isPending ? t('Saving…') : t('Save')}
          </Button>
        </fieldset>
      )}
      {configured && !probe && (
        <div className="mt-2 flex gap-2">
          <Button variant="outline" size="sm" onClick={() => check.mutate()}
                  disabled={check.isPending}>
            {t('Change library')}
          </Button>
          <Button variant="outline" size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => remove.mutate()} disabled={remove.isPending}>
            {t('Disconnect')}
          </Button>
        </div>
      )}
      <LiveStatus tone="error" className="mt-2 text-xs">{error}</LiveStatus>
      {msg && !error && <p className="mt-2 text-xs text-muted-foreground">{msg}</p>}
    </Card>
  )
}
