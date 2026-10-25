// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Project } from '@/api'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import MethodsPanel from '@/components/reporting/MethodsPanel'
import DisclosurePanel from '@/components/reporting/DisclosurePanel'
import DeviationsPanel from '@/components/reporting/DeviationsPanel'
import ChecklistsPanel from '@/components/reporting/ChecklistsPanel'

/** The last step of the pipeline: what goes into the manuscript.
 *
 * Three things a finished review owes its paper, all written from what the app
 * recorded rather than from what anyone remembers: the Methods section, the AI
 * disclosure statement, and the register of amendments to the planned methods
 * (PRISMA item 24c) — where the pipeline's own timestamps ask the questions and
 * the team supplies the reasons. */
export default function ReportingPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const [tab, setTab] = useState<'methods' | 'disclosure' | 'deviations' | 'checklists'>('methods')

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Reporting')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-3xl text-sm text-muted-foreground">
        {t('What your manuscript owes its readers, drafted from this project\'s own record: how the review was conducted, how AI was used to conduct it, and where it departed from its protocol. The drafts are drafts — you sign them, not the app.')}
      </p>

      <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}
            className="mb-4">
        <TabsList>
          <TabsTrigger value="methods">{t('Methods section')}</TabsTrigger>
          <TabsTrigger value="disclosure">{t('AI disclosure')}</TabsTrigger>
          <TabsTrigger value="deviations">{t('Amendments')}</TabsTrigger>
          <TabsTrigger value="checklists">{t('Checklists')}</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === 'methods' && <MethodsPanel pid={pid} />}
      {tab === 'disclosure' && <DisclosurePanel pid={pid} />}
      {tab === 'deviations' && <DeviationsPanel pid={pid} />}
      {tab === 'checklists' && <ChecklistsPanel pid={pid} />}
    </div>
  )
}
