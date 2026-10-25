// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Star } from 'lucide-react'
import { api, ApiError, type Credential, type JobInfo, type ProvidersInfo } from '@/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'

/** Provider key cards for one scope: global (projectId null, app admin) or
 * project (projectId set, project admin) — project keys override global ones. */
export function LlmProviderGrid({ projectId }: { projectId: number | null }) {
  const { t } = useTranslation()
  const { data: info } = useQuery<ProvidersInfo>({
    queryKey: ['llm-providers'],
    queryFn: () => api.get('/api/llm/providers'),
  })
  const { data: credentials = [] } = useQuery<Credential[]>({
    queryKey: ['llm-credentials', projectId],
    queryFn: () => api.get(
      `/api/llm/credentials${projectId != null ? `?project_id=${projectId}` : ''}`),
  })

  if (!info) return <p className="text-muted-foreground">{t('Loading…')}</p>

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {info.providers.map((provider) => (
        <ProviderCard
          key={provider}
          provider={provider}
          info={info}
          projectId={projectId}
          credential={credentials.find((c) => c.provider === provider) ?? null}
        />
      ))}
    </div>
  )
}

function ProviderCard({
  provider, info, credential, projectId,
}: {
  provider: string
  info: ProvidersInfo
  credential: Credential | null
  projectId: number | null
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const meta = info.meta[provider] ?? { label: provider, needs_key: true, needs_url: false }
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(credential?.base_url || info.default_local_url)
  const [model, setModel] = useState(credential?.default_model ?? info.default_models[provider])
  const [testState, setTestState] = useState<string>('')
  const eventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => () => eventSourceRef.current?.close(), [])
  // keep the field in sync with the stored model (on load and after a save)
  useEffect(() => {
    if (credential) {
      setModel(credential.default_model)
      if (credential.base_url) setBaseUrl(credential.base_url)
    }
  }, [credential?.id, credential?.default_model, credential?.base_url])  // eslint-disable-line

  const modelChanged = !!credential && model.trim() !== ''
    && model.trim() !== credential.default_model
  const urlChanged = meta.needs_url && !!credential
    && baseUrl.trim().replace(/\/+$/, '') !== credential.base_url
  // a hosted provider saves on a pasted key; a self-hosted one on its URL
  const canSave = meta.needs_key
    ? !!apiKey
    : !!baseUrl.trim() && (!credential || urlChanged || !!apiKey)

  // invalidate every scope: a project save may change which key wins
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['llm-credentials'] })

  const save = useMutation({
    mutationFn: () =>
      api.put<Credential>('/api/llm/credentials', {
        provider, api_key: apiKey, default_model: model, project_id: projectId,
        base_url: meta.needs_url ? baseUrl.trim() : '',
      }),
    onSuccess: () => {
      invalidate()
      setApiKey('')
      setTestState('')
    },
  })

  const saveModel = useMutation({
    mutationFn: () => api.post(
      `/api/llm/credentials/${credential!.id}/model`, { default_model: model.trim() }),
    onSuccess: invalidate,
  })

  const makeDefault = useMutation({
    mutationFn: () => api.post(`/api/llm/credentials/${credential!.id}/default`),
    onSuccess: invalidate,
  })

  const removeKey = useMutation({
    mutationFn: () => api.del(`/api/llm/credentials/${credential!.id}`),
    onSuccess: () => { invalidate(); setTestState('') },
  })

  const testKey = async () => {
    if (!credential) return
    setTestState(t('Testing…'))
    try {
      const { job_id } = await api.post<{ job_id: number }>(
        `/api/llm/credentials/${credential.id}/test`,
      )
      const es = new EventSource(`/api/jobs/${job_id}/stream`, { withCredentials: true })
      eventSourceRef.current = es
      es.onmessage = (event) => {
        const job = JSON.parse(event.data) as JobInfo
        if (job.status === 'running' || job.status === 'queued') {
          setTestState(job.message || t('Testing…'))
        } else if (job.status === 'done') {
          setTestState(t('✓ Key works'))
          es.close()
          // fetch the reply for display
          api.get<JobInfo>(`/api/jobs/${job.id}`).then((j) => {
            const reply = (j.result as { reply?: string }).reply
            if (reply) setTestState(t('✓ Key works — model replied: "{{reply}}"', { reply: reply.slice(0, 60) }))
          })
        } else {
          setTestState(`✗ ${job.error.split('\n')[0] || t('Test failed')}`)
          es.close()
        }
      }
      es.onerror = () => {
        es.close()
        setTestState((s) => (s.startsWith('✓') || s.startsWith('✗') ? s : t('✗ Connection lost')))
      }
    } catch (e) {
      setTestState(`✗ ${e instanceof ApiError ? e.message : t('Test failed')}`)
    }
  }

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold text-foreground">{meta.label}</h2>
        <span className="flex items-center gap-1">
          {credential?.is_default && (
            <Badge title={projectId != null
              ? t('AI features in this project use this key')
              : t('AI features use this key unless a project overrides it')}>
              <Star className="size-3" /> {t('used for AI jobs')}
            </Badge>
          )}
          {credential && (
            <Badge variant="outline">{meta.needs_key ? t('key stored') : t('endpoint stored')}</Badge>
          )}
        </span>
      </div>
      <form
        onSubmit={(e) => { e.preventDefault(); save.mutate() }}
        className="space-y-3"
      >
        {meta.needs_url && (
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">{t('Endpoint URL')}</label>
            <Input
              type="url"
              placeholder={info.default_local_url}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="font-mono"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {t('Any server speaking the OpenAI chat API: Ollama ({{url}}), LM Studio, vLLM, llama.cpp, OpenRouter… Nothing leaves that server. A full-text call sends up to about 15k tokens: raise the model context window (Ollama: num_ctx) or the text is silently cut.', { url: info.default_local_url })}
            </p>
          </div>
        )}
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {meta.needs_key ? t('API key') : t('API key (optional)')}
          </label>
          <Input
            type="password"
            placeholder={credential ? t('Replace stored key…')
              : meta.needs_key ? t('Paste API key') : t('Only if your server requires one')}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">{t('Default model')}</label>
          <Input
            list={`models-${provider}-${projectId ?? 'global'}`}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="font-mono"
          />
          <datalist id={`models-${provider}-${projectId ?? 'global'}`}>
            {info.suggested_models[provider]?.map((m) => <option key={m} value={m}>{m}</option>)}
          </datalist>
          {credential && (
            <div className="mt-1 flex items-center gap-2">
              <Button
                type="button" variant="outline" size="sm"
                onClick={() => saveModel.mutate()}
                disabled={!modelChanged || saveModel.isPending}
              >
                {saveModel.isPending ? t('Saving…') : t('Save model')}
              </Button>
              {modelChanged && (
                <span className="text-xs text-warning">{t('Unsaved model change')}</span>
              )}
              {saveModel.isSuccess && !modelChanged && (
                <span className="text-xs text-success">{t('✓ Model saved')}</span>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" disabled={!canSave || save.isPending}>
            {meta.needs_key ? t('Save key') : t('Save endpoint')}
          </Button>
          <Button
            type="button" variant="outline" size="sm"
            onClick={testKey} disabled={!credential}
          >
            {t('Test key')}
          </Button>
          {credential && !credential.is_default && (
            <Button
              type="button" variant="outline" size="sm"
              onClick={() => makeDefault.mutate()}
              disabled={makeDefault.isPending}
              title={t('AI features (screening suggestions, extraction prefill…) will use this key')}
            >
              {t('Use for AI jobs')}
            </Button>
          )}
          {credential && (
            <Button
              type="button" variant="outline" size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => {
                if (confirm(t('Remove the stored {{provider}} key?',
                              { provider: meta.label })))
                  removeKey.mutate()
              }}
              disabled={removeKey.isPending}
            >
              {t('Remove')}
            </Button>
          )}
        </div>
        {save.isError && (
          <p className="text-sm text-destructive">
            {save.error instanceof ApiError ? save.error.message : t('Save failed')}
          </p>
        )}
        {testState && (
          <p className={cn('text-sm',
            testState.startsWith('✗') ? 'text-destructive' : 'text-muted-foreground')}>
            {testState}
          </p>
        )}
      </form>
    </Card>
  )
}
