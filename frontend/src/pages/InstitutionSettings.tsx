// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type User } from '../api'
import {
  ServerInstitutionsEditor, type ServerInstitution,
} from '@/components/InstitutionAccess'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

/** App-wide institutional access (Administration). These entries are stored on
 * the server, encrypted, and inherited by every project — until now they could
 * only be *seen*, read-only, from a project's full-text settings, with no
 * screen to add or repair one. Personal, browser-held credentials live on the
 * "My institutional access" page instead. */
export default function InstitutionSettings() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const isAppAdmin = !!me?.is_admin
  const { data: stored, isLoading } = useQuery<ServerInstitution[]>({
    queryKey: ['global-institutions'],
    queryFn: () => api.get('/api/fulltext/institutions'),
    enabled: isAppAdmin,
  })
  const [draft, setDraft] = useState<ServerInstitution[] | null>(null)
  const items = draft ?? stored ?? []
  const [status, setStatus] = useState('')

  const save = useMutation({
    mutationFn: () => api.put('/api/fulltext/institutions', {
      institutions: items.map((i) => ({
        name: i.name, ezproxy_url: i.ezproxy_url, username: i.username,
        password: i.password ?? '', scope: i.scope, auth_type: i.auth_type })),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global-institutions'] })
      // project pages show these as inherited institutions
      queryClient.invalidateQueries({ queryKey: ['fulltext-config'] })
      setDraft(null)
      setStatus(t('✓ Saved'))
    },
    onError: (e) => setStatus(e instanceof ApiError ? e.message : t('Save failed')),
  })

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Institutional access (app)')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Library proxies (EZproxy, OpenAthens, CAS) stored on the server and tried by every project of this instance when retrieving paywalled PDFs. Passwords are encrypted and never displayed again. For access that must stay yours alone, use My institutional access instead — it never leaves your browser.')}
        {!isAppAdmin && ' ' + t('Only an application admin can change them.')}
      </p>
      {isAppAdmin && (
        <Card className="max-w-2xl space-y-3 p-4">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
          ) : (
            <>
              <ServerInstitutionsEditor items={items} onChange={setDraft} />
              <div className="flex items-center gap-3">
                <Button onClick={() => save.mutate()} disabled={save.isPending}>
                  {t('Save settings')}
                </Button>
                {status && (
                  <span className={status.startsWith('✓')
                    ? 'text-sm text-success' : 'text-sm text-destructive'}>
                    {status}
                  </span>
                )}
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  )
}
