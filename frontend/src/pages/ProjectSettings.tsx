// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type Project, type PromptInfo, type User } from '../api'
import { MembersPanel } from './Projects'
import { HighlightSettings } from './Screening'
import { ProjectDatabasesPanel } from './DatabaseSettings'
import { LlmProviderGrid } from '@/components/LlmProviderCards'
import { LlmTaskRouting } from '@/components/LlmTaskRouting'
import { Switch } from '@/components/ui/switch'
import {
  InstitutionList, MyInstitutionsPanel, type ServerInstitution,
} from '@/components/InstitutionAccess'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { findFramework, findReviewType, useFramings } from '@/components/framing'
import { findRegistry, useRegistries } from '@/components/registries'
import AppraisalSettings from '@/components/appraisal/AppraisalSettings'
import { isSandbox, useInstance } from '@/components/DemoBanner'

/** Project-scoped settings, gathered in one place (admin only): general info,
 * members, project AI keys (override the global ones), highlight lists.
 * Global app settings live under Administration in the sidebar. */
export default function ProjectSettingsPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const { data: projects = [], isLoading } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => api.get('/api/projects'),
  })
  // the institutional-access tab edits *this* user's own credentials
  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const { data: instance } = useInstance()
  // demo visitors: no members, stored keys, institutional logins or prompt
  // edits (refused server-side) — the tabs that only hold those are hidden
  const sandbox = isSandbox(me, instance)
  const project = projects.find((p) => p.id === pid)

  if (isLoading) return <p className="text-muted-foreground">{t('Loading…')}</p>
  if (!project) {
    return <p className="text-sm text-muted-foreground">{t('Project not found (or archived).')}</p>
  }
  if (project.my_role !== 'admin') {
    return (
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {t('Project settings — {{name}}', { name: project.name })}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          {t("Only a project admin can change this project's settings. Ask one of the project admins if something needs adjusting.")}
        </p>
        {project.llm_reviewers_can_route && (
          <>
            <p className="mt-4 max-w-2xl text-sm text-muted-foreground">
              {t('The project admins let reviewers choose the AI model per task. Keys stay theirs; you only pick which model each AI feature runs on.')}
            </p>
            <LlmTaskRouting projectId={pid} canEdit />
          </>
        )}
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {t('Project settings — {{name}}', { name: project.name })}
        </h1>
        {project.sync_role === 'satellite' && (
          <Badge
            variant="warning"
            title={t('Satellite copy — structural state managed by the coordinator')}
          >
            {t('satellite')}
          </Badge>
        )}
      </div>

      <SetupWizard project={project} />

      {sandbox && (
        <p className="mb-4 max-w-2xl rounded-md bg-warning/10 px-3 py-2 text-sm text-foreground">
          {t('Demo session: members, API keys, institutional access and prompt changes are not available here. The AI features run on the demo budget shown in the yellow banner.')}
        </p>
      )}

      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general">{t('General')}</TabsTrigger>
          {!sandbox && <TabsTrigger value="members">{t('Members')}</TabsTrigger>}
          <TabsTrigger value="db-keys">{t('Database keys')}</TabsTrigger>
          {!sandbox && <TabsTrigger value="access">{t('Institutional access')}</TabsTrigger>}
          {!sandbox && <TabsTrigger value="ai-keys">{t('AI keys')}</TabsTrigger>}
          <TabsTrigger value="appraisal">{t('Appraisal')}</TabsTrigger>
          <TabsTrigger value="ai-prompts">{t('AI prompts')}</TabsTrigger>
          <TabsTrigger value="highlights">{t('Highlights')}</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="pt-3">
          <GeneralSection project={project} />
        </TabsContent>

        <TabsContent value="appraisal" className="pt-3">
          <AppraisalTab pid={pid} project={project} />
        </TabsContent>

        <TabsContent value="members" className="pt-3">
          <Card className="max-w-2xl p-4">
            <p className="text-sm text-muted-foreground">
              {t('People with access to this project. Admins manage settings and structure; reviewers screen, vote and extract.')}
            </p>
            <MembersPanel project={project} />
          </Card>
        </TabsContent>

        <TabsContent value="db-keys" className="pt-3">
          <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
            {t('The databases of this review. API keys (Scopus, IEEE Xplore) apply to this project only and override the app-wide ones; every other database — including the ones you add here — works in assisted-manual mode: the app shows the translated query and you import the export file from the')}{' '}
            <Link to={`/projects/${pid}/search`} className="text-primary hover:underline">
              {t('Search page')}
            </Link>.
          </p>
          <ProjectDatabasesPanel projectId={pid} editable />
        </TabsContent>

        <TabsContent value="access" className="pt-3">
          <AccessSection projectId={pid} me={me} />
        </TabsContent>

        <TabsContent value="ai-keys" className="pt-3">
          <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
            {t('API keys used by the AI features of this project only. They override the app-wide keys (managed by the application admin under Administration). To share a project key with satellite co-reviewers, use the sharing toggles on the')}{' '}
            <Link to={`/projects/${pid}/sync`} className="text-primary hover:underline">
              {t('Synchronisation page')}
            </Link>.
          </p>
          <LlmProviderGrid projectId={pid} />
          <LlmTaskRouting projectId={pid} canEdit={project.sync_role !== 'satellite'} />
          <NoFallbackToggle project={project} />
          <ReviewersRouteToggle project={project} />
        </TabsContent>

        <TabsContent value="ai-prompts" className="pt-3">
          <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
            {t('The exact instructions each AI feature receives, for transparency. You can adapt them to this project — changes apply to future AI calls of this project only. The dynamic context (protocol text, checklists, evidence tables) and the JSON output format are appended by the app and cannot be edited.')}
          </p>
          <PromptsSection projectId={pid} />
        </TabsContent>

        <TabsContent value="highlights" className="pt-3">
          <p className="max-w-2xl text-sm text-muted-foreground">
            {t('Hand-curated word lists highlighted in titles and abstracts during screening (green = supports inclusion, red = signals exclusion).')}
          </p>
          <HighlightSettings projectId={pid} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

/** The three places institutional access can live, side by side — LitUbik has
 * server-stored proxies (app-wide and project-specific, shared with every
 * member) and browser-held personal ones, and "I don't see the access I
 * already entered" is what happens when a screen shows only one of them. */
function AccessSection({ projectId, me }: { projectId: number; me?: User }) {
  const { t } = useTranslation()
  const { data: config } = useQuery<{
    institutions: ServerInstitution[]
    inherited_institutions: ServerInstitution[]
  }>({
    queryKey: ['fulltext-config', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/fulltext/config`),
  })

  return (
    <div className="max-w-2xl space-y-6">
      <section>
        <h3 className="mb-1 text-sm font-medium text-foreground">
          {t('Shared access of this project (stored on the server)')}
        </h3>
        <p className="mb-2 text-xs text-muted-foreground">
          {t('Used for every member when retrieving paywalled PDFs. Edit them on the')}{' '}
          <Link to={`/projects/${projectId}/fulltext`}
                className="text-primary hover:underline">
            {t('Full-text page → Settings')}
          </Link>{t('; app-wide ones are managed under Administration → Institutional access (app).')}
        </p>
        <div className="space-y-2">
          <InstitutionList items={config?.institutions ?? []}
                           empty={t('No institution specific to this project.')} />
          <InstitutionList items={config?.inherited_institutions ?? []}
                           empty={t('No app-wide institution.')} />
        </div>
      </section>

      <section>
        <h3 className="mb-1 text-sm font-medium text-foreground">
          {t('My own access (this browser only)')}
        </h3>
        <p className="mb-2 text-xs text-muted-foreground">
          {t('Personal library credentials, kept in this browser and never sent to the server except during a retrieval run. The other members each add their own, here or under')}{' '}
          <Link to="/settings/institutions" className="text-primary hover:underline">
            {t('My institutional access')}
          </Link>.
        </p>
        <Card className="p-4">
          {me && <MyInstitutionsPanel userId={me.id} />}
        </Card>
      </section>
    </div>
  )
}

/** M4b — post-creation onboarding: shown when the page is opened with
 * ?setup=1 (right after "Create project"). Walks the admin through the three
 * kinds of access, each skippable — everything stays editable later in the
 * tabs below. */
/** First wizard step: it costs one click and it decides the vocabulary of
 * every later stage, so it is worth asking before the protocol is written. */
function FramingStep({ project }: { project: Project }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [reviewType, setReviewType] = useState(project.review_type)
  const [framework, setFramework] = useState(project.question_framework)
  const { data: framings } = useFramings()

  const save = useMutation({
    mutationFn: (patch: { review_type: string, question_framework: string }) =>
      api.put<Project>(`/api/projects/${project.id}`, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  })

  // picking a review type moves the framework to the one it usually goes with;
  // the framework select stays free afterwards
  const pickType = (key: string) => {
    setReviewType(key)
    const suggested = findReviewType(framings, key)?.default_framework ?? framework
    setFramework(suggested)
    save.mutate({ review_type: key, question_framework: suggested })
  }
  const pickFramework = (key: string) => {
    setFramework(key)
    save.mutate({ review_type: reviewType, question_framework: key })
  }

  return (
    <>
      <p className="mb-3 text-sm text-muted-foreground">
        {t('These two settings decide the vocabulary of the whole review: how the protocol is structured, what the concept blocks are called, which extraction columns are offered, and what the Methods section claims the review is. They change nothing in the pipeline itself, and you can change them later in the General tab.')}
      </p>
      <FramingFields
        reviewType={reviewType} framework={framework}
        onReviewType={pickType} onFramework={pickFramework}
        disabled={project.sync_role === 'satellite'}
      />
    </>
  )
}


function SetupWizard({ project }: { project: Project }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [step, setStep] = useState(0)
  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  if (searchParams.get('setup') !== '1') return null

  const close = () => {
    searchParams.delete('setup')
    setSearchParams(searchParams, { replace: true })
  }
  const finish = () => navigate(`/projects/${project.id}/protocol`)

  const steps = [
    {
      title: t('1/4 — How this review frames its question'),
      body: <FramingStep project={project} />,
    },
    {
      title: t('2/4 — Institutional access (full-text PDFs)'),
      body: (
        <>
          <p className="mb-3 text-sm text-muted-foreground">
            {t('When the review reaches full-text retrieval, paywalled PDFs are fetched through your library proxy. Each member adds their own institution — credentials stay in their browser, never on the server. Reviewers joining later can add theirs too.')}
          </p>
          {me && <MyInstitutionsPanel userId={me.id} />}
        </>
      ),
    },
    {
      title: t('3/4 — Database API keys (Scopus, IEEE…)'),
      body: (
        <>
          <p className="mb-3 text-sm text-muted-foreground">
            {t('With a key, a closed database becomes an automatic source (counts and search via API). Without one, it simply stays in assisted-manual mode — the app shows the translated query and you import the export file. Keys usually come with your institution’s subscription. Web of Science, EBSCO and the others are already available without a key, and you can add any database this review needs.')}
          </p>
          <ProjectDatabasesPanel projectId={project.id} editable />
        </>
      ),
    },
    {
      title: t('4/4 — AI keys (optional)'),
      body: (
        <>
          <p className="mb-3 text-sm text-muted-foreground">
            {t('An AI key enables the optional assistants (screening suggestions, extraction pre-fill…) for every member of this project — reviewers use the access, never see the key. Skip this to run fully manual.')}
          </p>
          <LlmProviderGrid projectId={project.id} />
        </>
      ),
    },
  ]

  return (
    <Card className="mb-6 border-primary/40 p-5">
      <div className="mb-1 flex items-start justify-between gap-3">
        <h2 className="font-semibold text-foreground">
          {t('Set up access for “{{name}}”', { name: project.name })}
        </h2>
        <Button variant="ghost" size="sm" onClick={close}>
          {t('Configure later')}
        </Button>
      </div>
      <p className="mb-4 text-xs text-muted-foreground">
        {t('Four optional steps — everything can be changed anytime in the tabs below or on the Full-text page.')}
      </p>
      <h3 className="mb-2 text-sm font-medium text-foreground">{steps[step].title}</h3>
      {steps[step].body}
      <div className="mt-4 flex items-center gap-2">
        {step > 0 && (
          <Button variant="outline" size="sm" onClick={() => setStep(step - 1)}>
            {t('Back')}
          </Button>
        )}
        {step < steps.length - 1 ? (
          <Button size="sm" onClick={() => setStep(step + 1)}>{t('Next')}</Button>
        ) : (
          <Button size="sm" onClick={finish}>{t('Finish — go to Protocol')}</Button>
        )}
        <span className="text-xs text-muted-foreground">
          {t('Step {{n}} of {{total}}', { n: step + 1, total: steps.length })}
        </span>
      </div>
    </Card>
  )
}

function PromptsSection({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const { data: prompts = [], isLoading } = useQuery<PromptInfo[]>({
    queryKey: ['prompts', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/prompts`),
  })
  if (isLoading) return <p className="text-muted-foreground">{t('Loading…')}</p>
  return (
    <div className="max-w-3xl space-y-4">
      {prompts.map((p) => (
        <PromptCard key={p.key} projectId={projectId} prompt={p} />
      ))}
    </div>
  )
}

function PromptCard({ projectId, prompt }: { projectId: number; prompt: PromptInfo }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [text, setText] = useState(prompt.effective_text)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState('')

  // refresh local state after saves/resets elsewhere
  useEffect(() => { setText(prompt.effective_text) }, [prompt.effective_text])

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['prompts', projectId] })
  const save = useMutation({
    mutationFn: () => api.put(
      `/api/projects/${projectId}/prompts/${prompt.key}`, { text }),
    onSuccess: () => { invalidate(); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const reset = useMutation({
    mutationFn: () => api.del(`/api/projects/${projectId}/prompts/${prompt.key}`),
    onSuccess: () => { invalidate(); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Reset failed')),
  })

  const dirty = text !== prompt.effective_text
  const modified = prompt.override_text !== null

  return (
    <Card className="p-4">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start justify-between gap-2 text-left"
      >
        <span>
          <span className="flex items-center gap-2">
            <span className="font-semibold text-foreground">{t(prompt.label)}</span>
            {modified && <Badge variant="warning">{t('modified')}</Badge>}
          </span>
          <span className="mt-0.5 block text-sm text-muted-foreground">
            {t(prompt.description)}
          </span>
        </span>
        <span className="shrink-0 text-xs text-primary">
          {expanded ? t('Hide') : t('View / edit')}
        </span>
      </button>
      {expanded && (
        <div className="mt-3 space-y-2">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={Math.min(18, Math.max(6, text.split('\n').length + 1))}
            className="font-mono text-xs leading-relaxed"
          />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => save.mutate()}
                    disabled={!dirty || !text.trim() || save.isPending}>
              {save.isPending ? t('Saving…') : t('Save for this project')}
            </Button>
            {modified && (
              <Button variant="outline" size="sm"
                      onClick={() => reset.mutate()} disabled={reset.isPending}>
                {t('Reset to default')}
              </Button>
            )}
            {dirty && <span className="text-xs text-warning">{t('Unsaved changes')}</span>}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      )}
    </Card>
  )
}

/** Review type + question framework. They change the vocabulary of the app —
 * protocol slots, concept-block labels, extraction template, what the AI is
 * told, what the Methods draft claims the review is — and nothing in the
 * pipeline. Both facts are said out loud here rather than discovered later. */
function FramingFields({ reviewType, framework, onReviewType, onFramework, disabled }: {
  reviewType: string
  framework: string
  onReviewType: (v: string) => void
  onFramework: (v: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const { data: framings } = useFramings()
  const selectedType = findReviewType(framings, reviewType)
  const selectedFramework = findFramework(framings, framework)

  return (
    <div className="space-y-3 rounded-md border border-border bg-muted/40 p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('Review type')}
          </label>
          <Select value={reviewType} onValueChange={onReviewType} disabled={disabled}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(framings?.review_types ?? []).map((r) => (
                <SelectItem key={r.key} value={r.key}>{t(r.label)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('Question framework')}
          </label>
          <Select value={framework} onValueChange={onFramework} disabled={disabled}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(framings?.frameworks ?? []).map((f) => (
                <SelectItem key={f.key} value={f.key}>{t(f.label)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {selectedFramework && selectedFramework.slots.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('The protocol will be structured on:')}{' '}
          <span className="text-foreground">
            {selectedFramework.slots.map((s) => t(s.label)).join(' · ')}
          </span>
          {selectedFramework.citation && ` (${selectedFramework.citation})`}
        </p>
      )}

      {selectedType?.tooling_note && (
        <p className="rounded-md border border-border bg-background p-2 text-xs text-muted-foreground">
          <strong className="text-foreground">{t('Framing only — the pipeline is unchanged.')}</strong>{' '}
          {t('This setting changes how LitUbik talks to you and to the AI: labels, AI prompts, the protocol it extracts, the extraction columns it offers and the Methods draft it writes. It does not change what the app does. LitUbik runs one search strand, has no object for the a priori framework and no tool for coding data against it. Build the framework and do that coding outside LitUbik — the extraction table gives you columns to record theme fit, provenance and emergent themes — and the Methods draft will say so rather than credit the tool.')}
        </p>
      )}

      <p className="text-xs text-muted-foreground">
        {t('Changing the framework applies to the next protocol extraction — a protocol already extracted keeps the text it has, which stays editable by hand.')}
      </p>
    </div>
  )
}


/** ISO datetime -> the YYYY-MM-DD an <input type="date"> understands. Sliced
 * rather than parsed: a registration date is a calendar day, and running it
 * through the local timezone would move it. */
function dateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : ''
}


/** PRISMA 2020 item 24a: the register and the number, or an explicit "not
 * registered". The empty value is a third state — nobody answered — and the
 * Methods draft treats it differently from a declared absence, so the form
 * never silently turns one into the other. */
function RegistrationFields({ registry, identifier, url, date, protocolUrl,
  onRegistry, onIdentifier, onUrl, onDate, onProtocolUrl, disabled }: {
  registry: string
  identifier: string
  url: string
  date: string
  protocolUrl: string
  onRegistry: (v: string) => void
  onIdentifier: (v: string) => void
  onUrl: (v: string) => void
  onDate: (v: string) => void
  onProtocolUrl: (v: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const { data: registries } = useRegistries()
  const selected = findRegistry(registries, registry)
  const registered = registry !== '' && registry !== 'none'

  return (
    <div className="space-y-3 rounded-md border border-border bg-muted/40 p-3">
      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          {t('Registration (PRISMA item 24a)')}
        </label>
        <Select value={registry || 'unset'} disabled={disabled}
                onValueChange={(v) => onRegistry(v === 'unset' ? '' : v)}>
          <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="unset">{t('Not answered yet')}</SelectItem>
            {(registries ?? []).map((r) => (
              <SelectItem key={r.key} value={r.key}>{t(r.label)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {registered && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Registration number')}
            </label>
            <Input value={identifier} disabled={disabled}
                   placeholder={selected?.id_hint ?? ''}
                   onChange={(e) => onIdentifier(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Registration date')}
            </label>
            <Input type="date" value={date} disabled={disabled}
                   onChange={(e) => onDate(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {selected?.has_url_template
                ? t('Record URL (optional — built from the number otherwise)')
                : t('Record URL')}
            </label>
            <Input type="url" value={url} disabled={disabled}
                   placeholder="https://…"
                   onChange={(e) => onUrl(e.target.value)} />
          </div>
        </div>
      )}

      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          {t('Protocol URL (PRISMA item 24b, optional)')}
        </label>
        <Input type="url" value={protocolUrl} disabled={disabled}
               placeholder="https://…"
               onChange={(e) => onProtocolUrl(e.target.value)} />
      </div>

      <p className="text-xs text-muted-foreground">
        {registry === ''
          ? t('Left unanswered, the Methods draft will leave a visible gap here rather than assume either way.')
          : registry === 'none'
            ? t('The Methods draft will state that the review was not registered — a limitation to declare, not a silence to keep.')
            : t('The Methods draft will name this register and cite this number.')}
      </p>
    </div>
  )
}


/** The appraisal settings need the member list, which the extraction config
 * endpoint already serves — no second members endpoint for the same list. */
function AppraisalTab({ pid, project }: { pid: number; project: Project }) {
  const { data } = useQuery<{ members: { user_id: number; display_name: string
                                         role: string }[] }>({
    queryKey: ['extraction-config', pid],
    queryFn: () => api.get(`/api/projects/${pid}/extraction/config`),
  })
  return (
    <AppraisalSettings pid={pid} members={data?.members ?? []}
                       disabled={project.sync_role === 'satellite'} />
  )
}


/** AI routing: let reviewers (not only project admins) change the provider,
 * model and effort per task. Off by default: a model switch changes cost and
 * behaviour for the whole team. */
function ReviewersRouteToggle({ project }: { project: Project }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const toggle = useMutation({
    mutationFn: (value: boolean) =>
      api.put<Project>(`/api/projects/${project.id}`, { llm_reviewers_can_route: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setError('')
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  return (
    <Card className="mt-4 max-w-2xl p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold text-foreground">{t('Reviewers may change the AI model per task')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t('By default only project admins change which provider, model and effort each AI task runs on. Turn this on to let every reviewer of the project adjust it from their Settings page — they still never see the keys.')}
          </p>
          {error && <p className="mt-1 text-sm text-destructive">{error}</p>}
        </div>
        <Switch
          checked={project.llm_reviewers_can_route}
          disabled={toggle.isPending || project.sync_role === 'satellite'}
          onCheckedChange={(v) => toggle.mutate(v)}
          aria-label={t('Reviewers may change the AI model per task')}
        />
      </div>
    </Card>
  )
}


/** AI keys: use only the key marked for AI jobs, never another provider.
 * What a team on a self-hosted model needs: a cloud key configured for
 * something else must not take over the day the local server is down. */
function NoFallbackToggle({ project }: { project: Project }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const toggle = useMutation({
    mutationFn: (value: boolean) =>
      api.put<Project>(`/api/projects/${project.id}`, { llm_no_fallback: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setError('')
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  return (
    <Card className="mt-4 max-w-2xl p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold text-foreground">{t('Never fall back to another provider')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t('By default, when the key marked for AI jobs fails (server down, no credit), the next configured key takes over — including an app-wide cloud key. Turn this on when the corpus must stay on your own model: the failure is reported instead.')}
          </p>
          {error && <p className="mt-1 text-sm text-destructive">{error}</p>}
        </div>
        <Switch
          checked={project.llm_no_fallback}
          disabled={toggle.isPending || project.sync_role === 'satellite'}
          onCheckedChange={(v) => toggle.mutate(v)}
          aria-label={t('Never fall back to another provider')}
        />
      </div>
    </Card>
  )
}

function GeneralSection({ project }: { project: Project }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description)
  const [researchQuestion, setResearchQuestion] = useState(project.research_question)
  const [reviewType, setReviewType] = useState(project.review_type)
  const [framework, setFramework] = useState(project.question_framework)
  const [registry, setRegistry] = useState(project.registry)
  const [registrationId, setRegistrationId] = useState(project.registration_id)
  const [registrationUrl, setRegistrationUrl] = useState(project.registration_url)
  // <input type="date"> speaks YYYY-MM-DD; the API speaks ISO datetimes
  const [registeredAt, setRegisteredAt] = useState(dateInput(project.registered_at))
  const [protocolUrl, setProtocolUrl] = useState(project.protocol_url)
  const [error, setError] = useState('')
  const isSatellite = project.sync_role === 'satellite'

  // re-seed the form when switching project
  useEffect(() => {
    setName(project.name)
    setDescription(project.description)
    setResearchQuestion(project.research_question)
    setReviewType(project.review_type)
    setFramework(project.question_framework)
    setRegistry(project.registry)
    setRegistrationId(project.registration_id)
    setRegistrationUrl(project.registration_url)
    setRegisteredAt(dateInput(project.registered_at))
    setProtocolUrl(project.protocol_url)
    setError('')
  }, [project.id])  // eslint-disable-line

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['projects'] })
    queryClient.invalidateQueries({ queryKey: ['projects', 'archived'] })
  }
  const save = useMutation({
    mutationFn: () => api.put<Project>(`/api/projects/${project.id}`, {
      name, description, research_question: researchQuestion,
      review_type: reviewType, question_framework: framework,
      registry, registration_id: registrationId,
      registration_url: registrationUrl, protocol_url: protocolUrl,
      // sent explicitly as null so clearing the field clears the date —
      // omitting a key means "leave it alone" on this endpoint
      registered_at: registeredAt ? `${registeredAt}T00:00:00Z` : null,
    }),
    onSuccess: () => { invalidate(); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const archive = useMutation({
    mutationFn: () => api.post(`/api/projects/${project.id}/archive`),
    onSuccess: () => { invalidate(); navigate('/') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Archive failed')),
  })

  const dirty = name !== project.name || description !== project.description
    || researchQuestion !== project.research_question
    || reviewType !== project.review_type
    || framework !== project.question_framework
    || registry !== project.registry
    || registrationId !== project.registration_id
    || registrationUrl !== project.registration_url
    || registeredAt !== dateInput(project.registered_at)
    || protocolUrl !== project.protocol_url

  return (
    <div className="max-w-2xl space-y-4">
      <Card className="p-4">
        <form
          onSubmit={(e) => { e.preventDefault(); save.mutate() }}
          className="space-y-3"
        >
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Project name')}
            </label>
            <Input required value={name} disabled={isSatellite}
                   onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Description')}
            </label>
            <Textarea value={description} disabled={isSatellite}
                      onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Research question')}
            </label>
            <Textarea value={researchQuestion} disabled={isSatellite}
                      onChange={(e) => setResearchQuestion(e.target.value)} />
          </div>
          <FramingFields
            reviewType={reviewType} framework={framework}
            onReviewType={setReviewType} onFramework={setFramework}
            disabled={isSatellite}
          />
          <RegistrationFields
            registry={registry} identifier={registrationId}
            url={registrationUrl} date={registeredAt} protocolUrl={protocolUrl}
            onRegistry={setRegistry} onIdentifier={setRegistrationId}
            onUrl={setRegistrationUrl} onDate={setRegisteredAt}
            onProtocolUrl={setProtocolUrl}
            disabled={isSatellite}
          />
          {isSatellite ? (
            <p className="text-xs text-muted-foreground">
              {t('Managed by the coordinator — these fields are locked on a satellite copy.')}
            </p>
          ) : (
            <Button type="submit" size="sm" disabled={!dirty || save.isPending}>
              {save.isPending ? t('Saving…') : t('Save changes')}
            </Button>
          )}
        </form>
      </Card>

      <Card className="border-destructive/40 p-4">
        <h2 className="text-sm font-semibold text-foreground">{t('Danger zone')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('Archiving hides the project from the home page (reversible). Restore it — or delete it permanently — from the Archived view of the Projects page.')}
        </p>
        <div className="mt-3">
          <Button variant="outline" size="sm"
                  onClick={() => archive.mutate()} disabled={archive.isPending}>
            {t('Archive project')}
          </Button>
        </div>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
