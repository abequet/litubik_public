// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type User } from '../api'
import { LlmProviderGrid } from '@/components/LlmProviderCards'
import { LlmTaskRouting } from '@/components/LlmTaskRouting'

/** Administration page: the GLOBAL AI keys (app-wide defaults). Project-level
 * overrides live in each project's Settings page. */
export default function LlmSettings() {
  const { t } = useTranslation()
  const { data: me } = useQuery<User | null>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('AI keys (app)')}
      </h1>
      <p className="mb-6 mt-1 max-w-2xl text-sm text-muted-foreground">
        {t('Store API keys for the AI providers you want to use. Keys are encrypted at rest and never displayed again. These global keys are the default for every project; a project can override them with its own keys in its Settings page. Only the application admin manages global keys.')}
      </p>
      {me?.is_admin ? (
        <>
          <LlmProviderGrid projectId={null} />
          <LlmTaskRouting projectId={null} canEdit />
        </>
      ) : (
        <p className="max-w-2xl text-sm text-muted-foreground">
          {t("Only an application admin can manage the global AI keys. To use your own key in a project where you are admin, open that project's Settings page.")}
        </p>
      )}
    </div>
  )
}
