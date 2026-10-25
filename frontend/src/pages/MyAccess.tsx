// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, type User } from '../api'
import { MyInstitutionsPanel } from '@/components/InstitutionAccess'
import { Card } from '@/components/ui/card'

/** Personal library access, app-wide (M4b). The same panel lives on the
 * Full-text page and in the project setup wizard, but it needed a permanent
 * home: the credentials are personal and browser-held, so they belong to the
 * account rather than to a project, and every member — not only admins — must
 * be able to reach them. */
export default function MyAccessPage() {
  const { t } = useTranslation()
  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('My institutional access')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Your library proxy (EZproxy, OpenAthens, CAS) is used to fetch paywalled PDFs during full-text retrieval, in every project you take part in. Credentials stay in this browser and are never stored on the server — they are sent once per retrieval run and forgotten.')}
      </p>
      <Card className="max-w-2xl p-4">
        {me && <MyInstitutionsPanel userId={me.id} />}
      </Card>
      <p className="mt-3 max-w-2xl text-xs text-muted-foreground">
        {t('Because they live in this browser, they follow neither your account to another computer nor your co-reviewers: each member adds their own on this page or on the')}{' '}
        <Link to="/" className="text-primary hover:underline">
          {t('Full-text page of a project')}
        </Link>.
      </p>
    </div>
  )
}
