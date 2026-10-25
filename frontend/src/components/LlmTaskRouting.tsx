// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type ProvidersInfo, type TaskRoute, type TaskRoutes } from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

const INHERIT = '__inherit__'

/** Per-task AI routing for one scope: which provider, model and effort each
 * AI feature runs on. Global scope (projectId null) is the app-wide default;
 * a project row overrides it for that project. */
export function LlmTaskRouting({ projectId, canEdit }: {
  projectId: number | null
  canEdit: boolean
}) {
  const { t } = useTranslation()
  const { data: info } = useQuery<ProvidersInfo>({
    queryKey: ['llm-providers'],
    queryFn: () => api.get('/api/llm/providers'),
  })
  const { data } = useQuery<TaskRoutes>({
    queryKey: ['llm-routes', projectId],
    queryFn: () => api.get(
      `/api/llm/routes${projectId != null ? `?project_id=${projectId}` : ''}`),
  })

  if (!info || !data) return <p className="text-muted-foreground">{t('Loading…')}</p>

  const tierLabel: Record<string, string> = {
    bulk: t('bulk'), reasoning: t('reasoning'),
  }

  return (
    <Card className="mt-4 p-4">
      <h2 className="font-semibold text-foreground">{t('Model per AI task')}</h2>
      <p className="mb-3 mt-1 text-sm text-muted-foreground">
        {projectId == null
          ? t('Which provider, model and reasoning effort each AI task runs on, for every project that does not override it. Tasks left on “inherited” use the best-ranked key with the tier model of its provider: a fast model for bulk tasks (screening, triage, translation, extraction), a stronger one for reasoning tasks (protocol, equations, narrative, report).')
          : t('Which provider, model and reasoning effort each AI task of this project runs on. Tasks left on “inherited” follow the app-wide routing, then the tier default of the best-ranked key.')}
      </p>
      {data.available_providers.length === 0 && (
        <p className="mb-3 text-sm text-warning">
          {t('No AI key is visible from here yet — the routing is saved but nothing will run until a key is stored.')}
        </p>
      )}
      <div className="space-y-2">
        {data.routes.map((row) => (
          <RouteRow
            key={`${row.task}-${row.route?.provider ?? ''}-${row.route?.model ?? ''}-${row.route?.effort ?? ''}`}
            row={row} info={info} projectId={projectId} canEdit={canEdit}
            available={data.available_providers} tierLabel={tierLabel}
          />
        ))}
      </div>
    </Card>
  )
}

function RouteRow({ row, info, projectId, canEdit, available, tierLabel }: {
  row: TaskRoute
  info: ProvidersInfo
  projectId: number | null
  canEdit: boolean
  available: string[]
  tierLabel: Record<string, string>
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [provider, setProvider] = useState(row.route?.provider ?? INHERIT)
  const [model, setModel] = useState(row.route?.model ?? '')
  const [effort, setEffort] = useState(row.route?.effort ?? info.default_effort)
  const [error, setError] = useState('')

  // when the provider changes, pre-fill the model with that provider's tier
  // default (the user can still type any id)
  useEffect(() => {
    if (provider === INHERIT) return
    if (provider !== row.route?.provider) {
      setModel(info.tier_models[provider]?.[row.tier] ?? info.default_models[provider] ?? '')
    } else {
      setModel(row.route?.model ?? '')
    }
  }, [provider])  // eslint-disable-line

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['llm-routes'] })
  const save = useMutation({
    mutationFn: () => api.put('/api/llm/routes', {
      task: row.task, provider, model: model.trim(), effort, project_id: projectId,
    }),
    onSuccess: () => { setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const reset = useMutation({
    mutationFn: () => api.del(
      `/api/llm/routes/${row.task}${projectId != null ? `?project_id=${projectId}` : ''}`),
    onSuccess: () => { setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  const dirty = provider === INHERIT
    ? !!row.route
    : (!row.route || row.route.provider !== provider
       || row.route.model !== model.trim() || row.route.effort !== effort)
  const canSave = canEdit && dirty && (provider === INHERIT || model.trim() !== '')
  const eff = row.effective
  const sourceLabel = {
    project: t('set for this project'),
    global: t('app-wide routing'),
    default: t('tier default'),
  }[eff.source] ?? eff.source
  const providerLabel = (p: string | null) => (p ? (info.meta[p]?.label ?? p) : '—')

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="font-medium text-foreground">{t(row.label)}</span>{' '}
          <Badge variant="outline" className="align-middle">{tierLabel[row.tier] ?? row.tier}</Badge>
          <p className="text-xs text-muted-foreground">{t(row.description)}</p>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('Runs on:')}{' '}
          <span className="font-mono text-foreground">
            {providerLabel(eff.provider)} · {eff.model ?? '—'} · {eff.effort}
          </span>{' '}
          ({sourceLabel})
          {eff.provider_missing && (
            <span className="ml-1 text-warning">
              {t('— no key for the routed provider, the best-ranked key is used instead')}
            </span>
          )}
        </p>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,2fr)_minmax(0,0.8fr)_auto] sm:items-end">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">{t('Provider')}</label>
          <Select value={provider} onValueChange={setProvider} disabled={!canEdit}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={INHERIT}>{t('Inherited')}</SelectItem>
              {info.providers.map((p) => (
                <SelectItem key={p} value={p}>
                  {info.meta[p]?.label ?? p}
                  {!available.includes(p) && ` (${t('no key')})`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">{t('Model')}</label>
          <Input
            list={`route-models-${row.task}-${provider}-${projectId ?? 'global'}`}
            value={provider === INHERIT ? '' : model}
            placeholder={provider === INHERIT ? (eff.model ?? '') : ''}
            onChange={(e) => setModel(e.target.value)}
            disabled={!canEdit || provider === INHERIT}
            className="font-mono text-sm"
          />
          {provider !== INHERIT && (
            <datalist id={`route-models-${row.task}-${provider}-${projectId ?? 'global'}`}>
              {info.suggested_models[provider]?.map((m) => <option key={m} value={m}>{m}</option>)}
            </datalist>
          )}
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">{t('Effort')}</label>
          <Select value={effort} onValueChange={setEffort}
                  disabled={!canEdit || provider === INHERIT}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {info.efforts.map((e) => (
                <SelectItem key={e} value={e}>{t(e)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-2">
          <Button
            type="button" size="sm"
            disabled={!canSave || save.isPending || reset.isPending}
            onClick={() => (provider === INHERIT ? reset.mutate() : save.mutate())}
          >
            {save.isPending || reset.isPending ? t('Saving…') : t('Save')}
          </Button>
          {row.route && canEdit && (
            <Button
              type="button" size="sm" variant="outline"
              disabled={reset.isPending}
              onClick={() => reset.mutate()}
              title={t('Back to the inherited routing')}
            >
              {t('Reset')}
            </Button>
          )}
        </div>
      </div>
      {error && <p className="mt-1 text-sm text-destructive">{error}</p>}
    </div>
  )
}
