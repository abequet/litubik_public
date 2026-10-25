// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type InstanceInfo } from '../api'

/**
 * AGPLv3 §13: whoever interacts with this instance over a network must be
 * offered the Corresponding Source of the version being served. Rendering it
 * from /api/instance means the offer follows every deployment, instead of
 * relying on the operator to publish it themselves.
 */
export default function SourceNotice() {
  const { t } = useTranslation()
  const { data } = useQuery<InstanceInfo>({
    queryKey: ['instance'],
    queryFn: () => api.get('/api/instance'),
    staleTime: Infinity,
  })
  if (!data?.source_url) return null
  return (
    <p className="px-3 pb-2 pt-1 text-xs leading-snug text-muted-foreground">
      LitUbik v{data.version} · {data.license} ·{' '}
      <a href={data.source_url} target="_blank" rel="noreferrer"
         className="underline underline-offset-2 hover:text-foreground">
        {t('Source code')}
      </a>
    </p>
  )
}
