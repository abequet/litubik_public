// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useWorkHeartbeat } from '../useWorkHeartbeat'
import { Sparkles } from 'lucide-react'
import {
  api, ApiError,
  type Annotation, type Criterion, type ExclusionReason, type Project,
  type ProtocolDetail, type ProtocolSummary,
} from '../api'
import PdfViewer, { type NewAnnotation } from '../components/PdfViewer'
import { usePdfWindow } from '../components/PdfWindow'
import TagChips from '../components/TagChips'
import ReplacePdfButton from '../components/ReplacePdfButton'
import {
  LeadSettings, SharesCard, evenWeights, weightsTotal, type Share,
} from '../components/ScreeningLots'
import { ArbiterPicker, canResolveConflicts } from '../components/ArbiterPicker'
import {
  AgreementMatrices, ReviewerProgress, type PairMatrix, type ReviewerStat,
} from '../components/ScreeningDashboard'
import {
  JustResolvedBanner, ReopenConflictButton, type ResolvedConflict,
} from '../components/ConflictUndo'
import {
  HL_GREEN, HL_RED, highlight, type HighlightFamily,
} from '@/lib/highlight'
import { cn } from '@/lib/utils'
import { useShortcutsEnabled } from '@/lib/shortcuts'
import LiveStatus from '../components/LiveStatus'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Segmented } from '@/components/ui/segmented'
import { Stat } from '@/components/ui/stat'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface ConfigInfo {
  config: {
    id: number
    stage: string
    round: number
    allocation: 'all' | 'dual' | 'single_overlap' | 'lead'
    overlap_pct: number
    conflict_resolution: 'consensus' | 'arbiter'
    arbiter_ids: number[] | null
    ai_enabled: boolean
    ai_reveal: 'always' | 'after_vote'
    reviewer_ids: number[]
    lead_user_id: number | null
    weights: Record<string, number> | null
    anonymous: boolean
    status: 'draft' | 'active'
    started_at: string | null
  } | null
  /** anonymous reviewers: the names in every payload are pseudonyms */
  names_hidden: boolean
  members: { user_id: number; display_name: string; role: string }[]
  eligible_records: number
  n_votes: number
  me: number
  my_role: string
  round: number
  rounds: number[]
}

interface QueueItem {
  id: number
  doi: string | null
  title: string
  authors: string[]
  year: number | null
  journal: string
  abstract: string
  fulltext_status: string
  has_pdf: boolean
  oa_url: string
  /** "decide later" — pushed to the back of my queue, now back on top */
  skipped?: boolean
}

interface CostInfo {
  cost_label: string
  cost_usd: number
  model: string
  provider: string
  tokens_in: number
  tokens_out: number
  estimated: boolean
}

interface Suggestion {
  revealed_early?: boolean
  decision: string
  confidence: number
  criteria: { code: string; assessment: string; note?: string }[]
  reasons: string[]
  justification: string
  warning?: string
  analysis?: string
  cost?: CostInfo | null
}

const STAGE = 'ft'

function useValidatedCriteria(projectId: number): Criterion[] {
  const { data: protocols = [] } = useQuery<ProtocolSummary[]>({
    queryKey: ['protocols', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/protocols`),
  })
  const validated = protocols
    .filter((p) => p.validated_at)
    .sort((a, b) => (b.validated_at! > a.validated_at! ? 1 : -1))[0]
  const { data: detail } = useQuery<ProtocolDetail>({
    queryKey: ['protocol', projectId, validated?.id],
    queryFn: () => api.get(`/api/projects/${projectId}/protocols/${validated!.id}`),
    enabled: validated !== undefined,
  })
  return detail?.criteria ?? []
}

export default function FulltextScreeningPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  type Tab = 'screen' | 'conflicts' | 'dashboard' | 'settings'
  const [tab, setTab] = useState<Tab>('screen')
  useWorkHeartbeat(pid, tab === 'conflicts' ? 'conflicts' : 'ft')
  const [roundChoice, setRoundChoice] = useState<number | null>(null)  // null = latest
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data: info } = useQuery<ConfigInfo>({
    queryKey: ['ftscreen-config', pid, roundChoice],
    queryFn: () => api.get(`/api/projects/${pid}/screening/config?stage=${STAGE}`
      + (roundChoice !== null ? `&round=${roundChoice}` : '')),
  })
  const round = info?.round ?? 1
  const isAdmin = info?.my_role === 'admin'
  const active = info?.config?.status === 'active'
  // deep link from the pipeline menu's snowballing sub-steps (?round=N)
  const [searchParams] = useSearchParams()
  const urlRound = searchParams.get('round')
  useEffect(() => {
    if (urlRound) setRoundChoice(Number(urlRound))
  }, [urlRound])

  useEffect(() => {
    if (info && !active) setTab(isAdmin ? 'settings' : 'screen')
  }, [info?.config?.status])  // eslint-disable-line

  const tabs: { id: Tab; label: string }[] = [
    { id: 'screen', label: t('Screen') },
    { id: 'conflicts', label: t('Conflicts') },
    { id: 'dashboard', label: t('Dashboard') },
    ...(isAdmin ? [{ id: 'settings' as Tab, label: t('Settings') }] : []),
  ]

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Full-text screening')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Assess each retrieved report against the protocol. Every exclusion needs a primary reason (PRISMA); highlights are shared with the whole team once the record is complete. Select text in the PDF and right-click to add a shared comment. The 📚 PDFs library lives in the pipeline bar, on every step.')}
      </p>
      {info?.names_hidden && (
        <p className="mb-4 max-w-2xl rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
          {t('Anonymous reviewers: names are hidden until this round is complete — every vote, pair and count is shown under a pseudonym, your own included.')}
        </p>
      )}
      {info && info.rounds.length > 1 && (
        <div className="mb-3 flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{t('Round')}</span>
          <Segmented
            value={round}
            onChange={setRoundChoice}
            options={info.rounds.map((r) => ({
              value: r,
              label: `r${r}${r > 1 ? ` · ${t('snowballing')}` : ''}`,
            }))}
          />
        </div>
      )}
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="mb-6">
        <TabsList>
          {tabs.map((tb) => (
            <TabsTrigger key={tb.id} value={tb.id}>{tb.label}</TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {!info ? <p className="text-muted-foreground">{t('Loading…')}</p> : (
        <>
          {tab === 'screen' && (active
            ? <ScreenTab projectId={pid} round={round}
                         aiEnabled={!!info.config?.ai_enabled}
                     afterVote={info.config?.ai_reveal === 'after_vote'} />
            : <p className="text-sm text-muted-foreground">
                {t('Full-text screening has not been started yet')}
                {isAdmin ? ` ${t('— configure it in the Settings tab.')}` : '.'}
              </p>)}
          {tab === 'conflicts' && (active
            ? <ConflictsTab projectId={pid} round={round}
                mode={info.config!.conflict_resolution}
                canResolve={canResolveConflicts(info.config!, info.members, info.me, isAdmin)} />
            : <p className="text-sm text-muted-foreground">{t('Not started.')}</p>)}
          {tab === 'dashboard' && <DashboardTab projectId={pid} round={round} />}
          {tab === 'settings' && isAdmin && (
            <SettingsTab projectId={pid} info={info} round={round} />
          )}
        </>
      )}
    </div>
  )
}

// ---- settings -------------------------------------------------------------------

function SettingsTab({ projectId, info, round }: {
  projectId: number
  info: ConfigInfo
  round: number
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const c = info.config
  const [allocation, setAllocation] = useState(c?.allocation ?? 'all')
  const [overlap, setOverlap] = useState(c?.overlap_pct ?? 20)
  const [resolution, setResolution] = useState(c?.conflict_resolution ?? 'consensus')
  const [arbiters, setArbiters] = useState<number[]>(c?.arbiter_ids ?? [])
  const [ai, setAi] = useState(c?.ai_enabled ?? false)
  const [afterVote, setAfterVote] = useState(c?.ai_reveal === 'after_vote')
  const [anonymous, setAnonymous] = useState(c?.anonymous ?? false)
  const [reviewers, setReviewers] = useState<number[]>(
    c?.reviewer_ids?.length ? c.reviewer_ids : info.members.map((m) => m.user_id))
  // allocation = lead: the reviewer who screens everything (default: me) and
  // the shares of the co-reviewers
  const [lead, setLead] = useState<number | null>(c?.lead_user_id ?? info.me)
  const [weights, setWeights] = useState<Record<string, number>>(
    c?.weights ?? evenWeights((c?.reviewer_ids?.length ? c.reviewer_ids
      : info.members.map((m) => m.user_id)).filter((uid) => uid !== (c?.lead_user_id ?? info.me))))
  const [error, setError] = useState('')
  const active = c?.status === 'active'
  const isLead = allocation === 'lead'
  const coReviewers = reviewers.filter((uid) => uid !== lead)
  const weightsOk = !isLead || coReviewers.length <= 1
    || Math.abs(weightsTotal(weights, coReviewers) - 100) < 0.05
  const leadOk = !isLead || (lead != null && reviewers.includes(lead) && coReviewers.length >= 1)
  const invalidate = () => {
    for (const k of ['ftscreen-config', 'ftscreen-stats', 'ftscreen-queue'])
      queryClient.invalidateQueries({ queryKey: [k, projectId] })
  }
  const { data: estimate } = useQuery<{ records_with_pdf: number
    records_without_pdf: number; approx_input_tokens: number
    cost?: CostInfo | null }>({
    queryKey: ['ftscreen-estimate', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/ai-estimate?stage=${STAGE}&round=${round}`),
    enabled: ai,
  })

  const save = useMutation({
    mutationFn: () => api.put(
      `/api/projects/${projectId}/screening/config?round=${round}`, {
      stage: STAGE, allocation, overlap_pct: overlap,
      conflict_resolution: resolution, ai_enabled: ai,
      arbiter_ids: resolution === 'arbiter' ? arbiters : [],
      ai_reveal: afterVote ? 'after_vote' : 'always', reviewer_ids: reviewers,
      anonymous, lead_user_id: isLead ? lead : null,
      weights: isLead && coReviewers.length > 1 ? Object.fromEntries(
        coReviewers.map((uid) => [String(uid), Number(weights[String(uid)]) || 0])) : null }),
    onSuccess: () => { invalidate(); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const start = useMutation({
    mutationFn: async () => {
      await save.mutateAsync()
      return api.post(
        `/api/projects/${projectId}/screening/start?stage=${STAGE}&round=${round}`)
    },
    onSuccess: () => { invalidate(); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Start failed')),
  })
  const reset = useMutation({
    mutationFn: () => api.post(
      `/api/projects/${projectId}/screening/reset?stage=${STAGE}&round=${round}`),
    onSuccess: () => { invalidate(); setError('') },
  })

  const optionRow = 'flex items-center gap-2 text-sm text-muted-foreground'

  return (
    <Card className="max-w-2xl space-y-4 p-5">
      {active && (
        <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">
          {t('Full-text screening is running (started {{date}}). Reset wipes all full-text votes and conflicts.',
             { date: new Date(c!.started_at!).toLocaleString() })}
        </p>
      )}
      <div>
        <p className="mb-1.5 text-sm font-medium text-foreground">{t('Who screens what')}</p>
        <RadioGroup value={allocation} disabled={active}
                    onValueChange={(v) => setAllocation(v as typeof allocation)}
                    className="gap-1.5">
          {([
            ['all', t('Everyone screens every report (kappa on the full set)')],
            ['dual', t('Two reviewers per report, spread across the team')],
            ['single_overlap', t('One reviewer per report + a % double-screened for the kappa')],
            ['lead', t('Lead reviewer — one reviewer screens every report, the others share the corpus (equal or declared shares)')],
          ] as const).map(([value, label]) => (
            <label key={value} className={optionRow}>
              <RadioGroupItem value={value} />
              {label}
              {value === 'single_overlap' && allocation === 'single_overlap' && (
                <Input type="number" min={0} max={100} value={overlap} disabled={active}
                       onChange={(e) => setOverlap(Number(e.target.value))}
                       className="h-7 w-16 px-2 text-xs" />
              )}
            </label>
          ))}
        </RadioGroup>
        {isLead && (
          <div className="mt-2">
            <LeadSettings members={info.members} reviewers={reviewers}
                          lead={lead} onLead={setLead}
                          weights={weights} onWeights={setWeights}
                          disabled={active} />
          </div>
        )}
      </div>
      <div>
        <p className="mb-1.5 text-sm font-medium text-foreground">{t('Conflict resolution')}</p>
        <RadioGroup value={resolution} disabled={active}
                    onValueChange={(v) => setResolution(v as typeof resolution)}
                    className="gap-1.5">
          {([
            ['consensus', t('Consensus — the reviewers record the joint decision')],
            ['arbiter', t('Arbiter — the arbiters named below decide (any project admin if none is named)')],
          ] as const).map(([value, label]) => (
            <label key={value} className={optionRow}>
              <RadioGroupItem value={value} />
              {label}
            </label>
          ))}
        </RadioGroup>
        {resolution === 'arbiter' && (
          <ArbiterPicker members={info.members} arbiters={arbiters}
                         onArbiters={setArbiters} disabled={active} />
        )}
      </div>
      <div>
        <p className="mb-1.5 text-sm font-medium text-foreground">
          {t('Reviewers')} ({reviewers.length})
        </p>
        <div className="flex flex-col gap-1.5">
          {info.members.map((m) => (
            <label key={m.user_id} className={optionRow}>
              <Checkbox disabled={active} checked={reviewers.includes(m.user_id)}
                        onCheckedChange={(v) => setReviewers(v
                          ? [...reviewers, m.user_id]
                          : reviewers.filter((id) => id !== m.user_id))} />
              {m.display_name} <span className="text-xs text-muted-foreground">({m.role})</span>
            </label>
          ))}
        </div>
      </div>
      <label className={cn(optionRow, 'items-start')}>
        <Checkbox disabled={active} checked={anonymous} className="mt-0.5"
                  onCheckedChange={(v) => setAnonymous(!!v)} />
        <span>
          {t('Anonymous reviewers')}
          <span className="text-muted-foreground/70">
            {' '}{t('— nobody, the admins included, sees who voted what nor who is paired with whom until the round is complete; names are replaced by “Reviewer 1, 2…” everywhere (conflicts, dashboard, notes, PRISMA activity). Frozen at the start. Pointless with two reviewers.')}
          </span>
        </span>
      </label>
      <label className={optionRow}>
        <Checkbox disabled={active} checked={ai}
                  onCheckedChange={(v) => setAi(!!v)} />
        {t('AI suggestions on click, from the PDF text (needs a validated protocol and an API key)')}
      </label>
      <label className={cn(optionRow, 'ml-6 items-start')}>
        <Checkbox disabled={!ai} checked={afterVote} className="mt-0.5"
                  onCheckedChange={(v) => {
                    setAfterVote(!!v)
                    if (active)
                      api.put(`/api/projects/${projectId}/screening/config/ai-reveal?stage=${STAGE}&round=${round}`,
                              { ai_reveal: v ? 'after_vote' : 'always' }).then(invalidate)
                  }} />
        <span>
          {t('Show the AI suggestion only after the vote')}
          <span className="text-muted-foreground/70">
            {' '}{t('— enforced server-side; a suggestion a co-reviewer already requested can be revealed on purpose, which is recorded (changeable while the round runs)')}
          </span>
        </span>
      </label>
      {ai && estimate && (
        <p className="-mt-2 ml-6 text-xs text-muted-foreground">
          {t('{{count}} report(s) have a stored PDF', { count: estimate.records_with_pdf })}
          {estimate.records_without_pdf > 0
            && ` (${t('{{count}} without one', { count: estimate.records_without_pdf })})`}
          {' '}{t('· ≈ {{tokens}} input tokens if you AI-screen them all',
                  { tokens: estimate.approx_input_tokens.toLocaleString() })}
          {estimate.cost ? ` (≈ ${estimate.cost.cost_label})` : ''}.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        {t('{{count}} report(s) included at title/abstract will enter full-text screening.',
           { count: info.eligible_records })}
      </p>
      <div className="flex gap-2">
        {!active && (
          <>
            <Button variant="outline" onClick={() => save.mutate()} disabled={save.isPending}>
              {t('Save')}
            </Button>
            <Button onClick={() => start.mutate()}
                    disabled={start.isPending || reviewers.length === 0 || !leadOk || !weightsOk}>
              {t('Start full-text screening')}
            </Button>
          </>
        )}
        {active && (
          <Button
            variant="outline"
            className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => {
              if (confirm(t('Reset full-text screening round {{round}}? Its {{count}} vote(s) and all its resolutions will be deleted.',
                            { round, count: info.n_votes })))
                reset.mutate()
            }}
          >
            {t('Reset full-text screening')}
          </Button>
        )}
      </div>
      <LiveStatus className="text-sm">{error}</LiveStatus>
    </Card>
  )
}

// ---- annotations hook -----------------------------------------------------------

function useAnnotations(projectId: number, recordId: number | undefined) {
  const queryClient = useQueryClient()
  const base = `/api/projects/${projectId}/records/${recordId}/annotations`
  const { data: annotations = [] } = useQuery<Annotation[]>({
    queryKey: ['annotations', projectId, recordId],
    queryFn: () => api.get(base),
    enabled: recordId !== undefined,
  })
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['annotations', projectId, recordId] })
  const create = useMutation({
    mutationFn: (a: NewAnnotation) => api.post(base, a),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`${base}/${id}`),
    onSuccess: invalidate,
  })
  return { annotations, create, remove }
}

// ---- screen tab -----------------------------------------------------------------

interface HistoryEntry {
  record: QueueItem
  decision: string
  reasons: string[]
  reason_labels: string[]
  note: string
  locked: boolean
}

function ScreenTab({ projectId, round, aiEnabled, afterVote }: {
  projectId: number
  round: number
  aiEnabled: boolean
  afterVote: boolean
}) {
  const { t } = useTranslation()
  const shortcuts = useShortcutsEnabled()
  const queryClient = useQueryClient()
  const { data: queue } = useQuery<{ total: number; done: number; skipped: number
    items: QueueItem[] }>({
    queryKey: ['ftscreen-queue', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/queue?stage=${STAGE}&limit=1&round=${round}`),
  })
  const { data: reasonData } = useQuery<{ reasons: ExclusionReason[]; notfound_code: string }>({
    queryKey: ['ftscreen-reasons', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/screening/reasons?stage=${STAGE}`),
  })
  const { data: myVotes = [] } = useQuery<HistoryEntry[]>({
    queryKey: ['ftscreen-my-votes', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/my-votes?stage=${STAGE}&round=${round}`),
  })
  const criteria = useValidatedCriteria(projectId)

  const [showHistory, setShowHistory] = useState(false)
  const [revisitIndex, setRevisitIndex] = useState<number | null>(null)
  const revisit = revisitIndex !== null ? myVotes[revisitIndex] ?? null : null
  const record = revisit?.record ?? queue?.items[0]
  const { annotations, create: createAnn, remove: removeAnn } =
    useAnnotations(projectId, record?.id)

  const [excluding, setExcluding] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [primary, setPrimary] = useState('')
  const [note, setNote] = useState('')
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const [error, setError] = useState('')
  // bumped after "Replace PDF" so the inline viewer reloads the new file (#T17)
  const [pdfVersion, setPdfVersion] = useState(0)
  // T14: the project's hand-curated red/green word lists, applied to the title
  const { data: hl } = useQuery<{ green: string[]; red: string[] }>({
    queryKey: ['highlights', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/highlights`),
  })
  const families: HighlightFamily[] = [
    { words: hl?.red ?? [], className: HL_RED },
    { words: hl?.green ?? [], className: HL_GREEN },
  ]

  const clearForm = () => {
    setExcluding(false); setSelected([]); setPrimary(''); setNote('')
    setSuggestion(null); setError('')
  }

  // after_vote rounds: what the server lets me see for this report — the
  // suggestion a co-reviewer already requested, or only that one exists
  const { data: cached } = useQuery<{ suggestion: Suggestion | null
    withheld?: boolean; available?: boolean }>({
    queryKey: ['ftscreen-suggestion', projectId, record?.id, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/records/${record!.id}/suggestion`
      + `?stage=${STAGE}&round=${round}`),
    enabled: aiEnabled && afterVote && record !== undefined,
  })
  useEffect(() => {
    if (aiEnabled && afterVote) setSuggestion(cached?.suggestion ?? null)
  }, [cached, record?.id, aiEnabled, afterVote])
  const withheld = afterVote && !revisit && !!cached?.withheld
  const reveal = useMutation({
    mutationFn: () => api.post<{ suggestion: Suggestion }>(
      `/api/projects/${projectId}/screening/records/${record!.id}/reveal?stage=${STAGE}&round=${round}`),
    onSuccess: (r) => {
      setSuggestion(r.suggestion)
      queryClient.invalidateQueries({ queryKey: ['ftscreen-suggestion', projectId, record?.id] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('AI failed')),
  })
  const [postVote, setPostVote] = useState<{
    title: string; decision: string; suggestion: Suggestion } | null>(null)

  const vote = useMutation({
    mutationFn: async (payload: { decision: string; reasons: string[] }) => {
      const voted = record!
      await api.post(`/api/projects/${projectId}/screening/vote?stage=${STAGE}&round=${round}`,
        { record_id: voted.id, decision: payload.decision,
          reasons: payload.reasons, justification: note })
      if (afterVote && aiEnabled && !revisit && !suggestion) {
        try {
          const r = await api.get<{ suggestion: Suggestion | null }>(
            `/api/projects/${projectId}/screening/records/${voted.id}/suggestion?stage=${STAGE}&round=${round}`)
          if (r.suggestion) setPostVote({ title: voted.title, decision: payload.decision, suggestion: r.suggestion })
        } catch { /* courtesy card only */ }
      }
    },
    onSuccess: () => {
      setRevisitIndex(null)
      clearForm()
      queryClient.invalidateQueries({ queryKey: ['ftscreen-suggestion', projectId] })
      queryClient.invalidateQueries({ queryKey: ['ftscreen-queue', projectId] })
      queryClient.invalidateQueries({ queryKey: ['ftscreen-my-votes', projectId] })
      queryClient.invalidateQueries({ queryKey: ['ftscreen-stats', projectId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Vote failed')),
  })

  // "decide later": the record stays in my queue but sinks to the back —
  // typically because the PDF is missing/unreadable and I'd rather get it
  // fixed than exclude it now
  const skip = useMutation({
    mutationFn: () =>
      api.post(`/api/projects/${projectId}/screening/skip?stage=${STAGE}&round=${round}`,
        { record_id: record!.id }),
    onSuccess: () => {
      clearForm()
      queryClient.invalidateQueries({ queryKey: ['ftscreen-queue', projectId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Skip failed')),
  })

  const openRevisit = (index: number) => {
    const entry = myVotes[index]
    if (!entry) return
    setRevisitIndex(index)
    setNote(entry.note)
    setSuggestion(null); setError('')
    if (entry.decision === 'exclude' && entry.reasons.length) {
      setExcluding(true); setSelected(entry.reasons); setPrimary(entry.reasons[0])
    } else {
      setExcluding(false); setSelected([]); setPrimary('')
    }
  }
  const goPrevious = () => {
    if (myVotes.length === 0) return
    const next = revisitIndex === null ? 0 : revisitIndex + 1
    if (next >= myVotes.length) return
    openRevisit(next)
  }
  const resumeQueue = () => {
    if (revisitIndex === null) return
    setRevisitIndex(null); clearForm()
  }
  const canVote = record !== undefined && !(revisit?.locked)

  const toggleReason = (code: string) => {
    setSelected((prev) => {
      const next = prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
      setPrimary((p) => (next.includes(p) ? p : next[0] ?? ''))
      return next
    })
  }
  const submitExclude = () => {
    if (!primary) return
    vote.mutate({ decision: 'exclude',
                  reasons: [primary, ...selected.filter((c) => c !== primary)] })
  }
  // the AI's exclusion reasons never pre-fill the form by themselves: the
  // reviewer asks for them (anchoring is a documented risk — LitFlow 2026)
  const validAiReasons = (s: Suggestion) => s.decision === 'exclude'
    ? s.reasons.filter((c) => (reasonData?.reasons || []).some((r) => r.code === c))
    : []
  const applyAiReasons = (s: Suggestion) => {
    const valid = validAiReasons(s)
    if (valid.length) { setExcluding(true); setSelected(valid); setPrimary(valid[0]) }
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (vote.isPending) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
      if (postVote) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Escape') {
          e.preventDefault(); setPostVote(null)
        }
        return
      }
      if (e.key === 'Backspace') goPrevious()
      if (e.key === 'Escape') { if (excluding) { setExcluding(false) } else resumeQueue() }
      if (!shortcuts) return  // WCAG 2.1.4: single-letter keys switched off ("?" menu)
      if (e.key === 'p') goPrevious()
      if (!canVote) return
      if (e.key === 'y' || e.key === 'i') vote.mutate({ decision: 'include', reasons: [] })
      if (e.key === 'n' || e.key === 'x') setExcluding(true)
      if (e.key === 's' && !revisit && !skip.isPending) skip.mutate()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [record?.id, vote.isPending, skip.isPending, myVotes.length, revisitIndex, canVote, excluding, postVote, shortcuts])  // eslint-disable-line

  if (!queue) return <p className="text-muted-foreground">{t('Loading queue…')}</p>
  const pct = queue.total ? Math.round((queue.done / queue.total) * 100) : 0
  const notFoundCode = reasonData?.notfound_code ?? 'NOTFOUND'

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button variant={showHistory ? 'default' : 'secondary'} size="sm"
                className="rounded-full"
                onClick={() => setShowHistory((v) => !v)}>
          {showHistory ? t('◂ History') : `${t('History')} (${myVotes.length})`}
        </Button>
        <Progress value={pct} className="flex-1" />
        <span className="text-xs tabular-nums text-muted-foreground">
          {queue.done}/{queue.total}
          {queue.skipped > 0 && (
            <span className="text-warning"> · {t('{{count}} skipped', { count: queue.skipped })}</span>
          )}
        </span>
      </div>

      {!revisit && record?.skipped && (
        <p className="mb-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-1.5 text-xs text-warning">
          {t("⏭ You skipped this report earlier — it's back for a decision.")}
        </p>
      )}

      <div className={showHistory ? 'grid items-start gap-4 lg:grid-cols-[16rem_1fr]' : undefined}>
      {showHistory && (
        <Card className="max-h-[78vh] overflow-y-auto p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            {t('Already screened ({{count}}) — click to revisit', { count: myVotes.length })}
          </p>
          {myVotes.length === 0 && (
            <p className="text-xs text-muted-foreground">{t('Nothing yet.')}</p>
          )}
          <ul className="space-y-1">
            {myVotes.map((entry, i) => (
              <li key={entry.record.id}>
                <button onClick={() => openRevisit(i)}
                        className={cn('w-full rounded-md border px-2 py-1.5 text-left text-xs',
                          revisitIndex === i
                            ? 'border-border bg-accent'
                            : 'border-transparent hover:bg-accent')}>
                  <span className={cn('inline-block w-14 font-medium',
                    entry.decision === 'include' ? 'text-success'
                      : entry.decision === 'exclude' ? 'text-destructive'
                      : 'text-warning')}>
                    {t(entry.decision)}
                  </span>
                  {entry.locked && <span title={t('Completed — read-only')}>🔒 </span>}
                  <span className="text-muted-foreground">
                    {entry.record.title.slice(0, 55)}
                    {entry.record.title.length > 55 ? '…' : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!record ? (
        <Card className="border-success/30 bg-success/10 p-6 text-sm text-success">
          <p>{t('✓ Nothing left in your queue — check the Conflicts tab or the Dashboard.')}</p>
          {myVotes.length > 0 && (
            <Button variant="outline" size="sm" onClick={goPrevious}
                    className="mt-3 border-success/40 text-success hover:bg-success/10 hover:text-success">
              {t('← Revisit my previous vote')} {shortcuts && <span className="opacity-60">(P)</span>}
            </Button>
          )}
        </Card>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          {/* PDF / report */}
          <Card className="h-[60vh] min-w-0 p-3 lg:h-[78vh]">
            {record.has_pdf ? (
              <PdfViewer
                fileUrl={`/api/projects/${projectId}/fulltext/records/${record.id}/file`
                  + (pdfVersion ? `?v=${pdfVersion}` : '')}
                annotations={annotations}
                onCreate={(a) => createAnn.mutate(a)}
                onDelete={(id) => removeAnn.mutate(id)} />
            ) : (
              <div className="grid h-full place-items-center p-6 text-center">
                <div>
                  <p className="mb-2 text-sm text-muted-foreground">
                    {t('No PDF stored for this report.')}
                  </p>
                  {record.oa_url && (
                    <a href={record.oa_url} target="_blank" rel="noreferrer"
                       className="text-sm text-primary hover:underline">
                      {t('Open the publisher page ↗')}
                    </a>
                  )}
                  <div className="mt-3">
                    <ReplacePdfButton projectId={projectId} recordId={record.id}
                                      hasPdf={false}
                                      onReplaced={() => setPdfVersion((v) => v + 1)} />
                  </div>
                  <p className="mt-3 text-xs text-muted-foreground">
                    {t('Have the PDF? Upload it above. Not now? Skip the report and it comes back later. If it cannot be obtained, exclude it with “{{reason}}”.',
                       { reason: reasonData?.reasons.find((r) => r.code === notFoundCode)?.label
                         ?? t('Full text not retrievable') })}
                  </p>
                </div>
              </div>
            )}
          </Card>

          {/* fixed action rail — buttons first so they never shift with the
              variable-height title card (matches the T/A screen) */}
          <div className="sticky top-4 space-y-2">
            {!excluding ? (
              <>
                <Button variant="success" className="w-full"
                        onClick={() => vote.mutate({ decision: 'include', reasons: [] })}
                        disabled={vote.isPending || !canVote}>
                  {t('Include')} {shortcuts && <span className="opacity-60">(Y)</span>}
                </Button>
                <Button variant="destructive" className="w-full"
                        onClick={() => setExcluding(true)}
                        disabled={vote.isPending || !canVote}>
                  {t('Exclude…')} {shortcuts && <span className="opacity-60">(N)</span>}
                </Button>
                {!revisit && (
                  <Button variant="outline" className="w-full"
                          onClick={() => skip.mutate()}
                          disabled={skip.isPending || vote.isPending || !canVote}
                          title={t('No decision now — the report moves to the back of your queue and comes around again (e.g. while the PDF gets fixed)')}>
                    {t('⏭ Skip — decide later')} {shortcuts && <span className="opacity-60">(S)</span>}
                  </Button>
                )}
              </>
            ) : (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3">
                <p className="mb-2 text-xs font-medium text-destructive">
                  {t('Exclusion reason — tick every reason, the primary (●) drives PRISMA.')}
                </p>
                <ul className="max-h-56 space-y-1 overflow-y-auto">
                  {(reasonData?.reasons || []).map((r) => {
                    const checked = selected.includes(r.code)
                    return (
                      <li key={r.code} className="flex items-start gap-1.5 text-xs">
                        <Checkbox checked={checked} className="mt-0.5"
                                  onCheckedChange={() => toggleReason(r.code)} />
                        <button type="button" title={t('Set as primary reason')}
                                aria-label={t('Set as primary reason')} aria-pressed={primary === r.code}
                                onClick={() => checked && setPrimary(r.code)}
                                className={cn('mt-0.5 h-3 w-3 shrink-0 rounded-full border',
                                  primary === r.code ? 'bg-destructive border-destructive'
                                    : 'border-input', checked ? '' : 'opacity-30')} />
                        <span className={r.kind === 'builtin' ? 'italic text-muted-foreground' : ''}>
                          <span className="font-mono font-medium">{r.code}</span> {r.label}
                        </span>
                      </li>
                    )
                  })}
                </ul>
                <div className="mt-2 flex gap-2">
                  <Button variant="destructive" size="sm" className="flex-1"
                          onClick={submitExclude}
                          disabled={!primary || vote.isPending || !canVote}>
                    {t('Confirm exclusion')}
                  </Button>
                  <Button variant="outline" size="sm"
                          onClick={() => { setExcluding(false); setSelected([]); setPrimary('') }}>
                    {t('Cancel')}
                  </Button>
                </div>
              </div>
            )}
            {revisit && (
              <div className={cn('flex items-start gap-2 rounded-md px-3 py-2 text-xs',
                revisit.locked ? 'bg-muted text-muted-foreground' : 'bg-warning/10 text-warning')}>
                <span className="flex-1">
                  {revisit.locked
                    ? <>{t('Completed — you voted “{{decision}}”', { decision: t(revisit.decision) })}
                        {revisit.reason_labels.length > 0
                          && ` (${revisit.reason_labels.join(', ')})`}. {t('Read-only.')}</>
                    : <>{t('Revisiting — you voted “{{decision}}”. Vote again to change it.',
                           { decision: t(revisit.decision) })}</>}
                </span>
                <button onClick={resumeQueue}
                        className="shrink-0 rounded-md border border-current/30 px-2 py-0.5 font-medium hover:bg-background/50">
                  {t('Resume →')} <span className="opacity-60">(Esc)</span>
                </button>
              </div>
            )}
            <Card className="p-3">
              <h2 className="text-sm font-semibold leading-snug text-foreground">
                {highlight(record.title, families)}
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {record.authors.slice(0, 4).join('; ')}
                {record.authors.length > 4 ? '…' : ''}
                {record.year ? ` · ${record.year}` : ''}
                {record.journal ? ` · ${record.journal}` : ''}
              </p>
              {record.doi && (
                <a href={`https://doi.org/${record.doi}`} target="_blank" rel="noreferrer"
                   className="break-all font-mono text-xs text-primary hover:underline">
                  {record.doi}
                </a>
              )}
              <TagChips projectId={projectId} recordId={record.id}
                        className="mt-1.5" />
              {record.has_pdf && (
                <div className="mt-1.5">
                  <ReplacePdfButton projectId={projectId} recordId={record.id}
                                    onReplaced={() => setPdfVersion((v) => v + 1)} />
                </div>
              )}
            </Card>

            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                      placeholder={t('Note for this vote (shown during conflict resolution)…')}
                      className="text-xs" />

            {aiEnabled && (!afterVote || !!revisit) && (
              <AiSuggestButton projectId={projectId} recordId={record.id}
                               round={round}
                               onResult={setSuggestion} onError={setError} />
            )}
            {withheld && !suggestion && (
              <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
                <Sparkles className="mr-1 inline size-3.5 text-primary" />
                {cached?.available
                  ? t('An AI suggestion exists for this record. In this round it is shown after your vote.')
                  : t('In this round the AI suggestion is shown after your vote.')}
                {cached?.available && (
                  <Button type="button" variant="outline" size="sm" className="mt-2 w-full"
                          onClick={() => reveal.mutate()} disabled={reveal.isPending}
                          title={t('Looking before you vote is allowed, and recorded in the AI-use journal so blind votes can be told apart.')}>
                    {reveal.isPending ? '…' : t('See the AI suggestion before voting')}
                  </Button>
                )}
              </div>
            )}
            {postVote && (
              <div className="rounded-md border border-border border-l-2 border-l-primary p-3 text-xs" aria-live="polite">
                <p className="font-medium text-foreground">
                  {t('You voted {{yours}} · the AI had suggested {{ai}} (confidence {{pct}} %)', {
                    yours: t(postVote.decision), ai: t(postVote.suggestion.decision),
                    pct: (postVote.suggestion.confidence * 100).toFixed(0) })}
                </p>
                {postVote.suggestion.justification && (
                  <p className="mt-1 text-muted-foreground">{postVote.suggestion.justification}</p>
                )}
                <p className="mt-1 text-muted-foreground">
                  {t('Your vote stands as cast. Shown afterwards so the suggestion could not anchor it.')}
                </p>
                <Button size="sm" className="mt-2 w-full" onClick={() => setPostVote(null)}>
                  {t('Next')} <span className="opacity-60">(Enter)</span>
                </Button>
              </div>
            )}
            {suggestion && (
              <div className="rounded-md border border-border border-l-2 border-l-primary bg-accent p-3 text-xs">
                {suggestion.revealed_early && (
                  <p className="mb-1 text-warning">
                    {t('Revealed before your vote — recorded in the AI-use journal.')}
                  </p>
                )}
                <p className="font-medium text-foreground">
                  <Sparkles className="mr-1 inline size-3.5 text-primary" />
                  {t('AI suggests:')} {t(suggestion.decision)}
                  <span className="font-normal text-muted-foreground"
                        title={t('Self-assessed by the model, not calibrated.')}>
                    {' '}({(suggestion.confidence * 100).toFixed(0)} %)
                  </span>
                </p>
                {suggestion.warning && (
                  <p className="mt-1 rounded bg-warning/15 px-2 py-1 text-warning">
                    ⚠ {suggestion.warning}
                  </p>
                )}
                <p className="mt-1 text-muted-foreground">{suggestion.justification}</p>
                {suggestion.reasons.length > 0 && (
                  <p className="mt-1 text-muted-foreground">
                    {t('Reasons:')} {suggestion.reasons.join(', ')}
                  </p>
                )}
                {canVote && validAiReasons(suggestion).length > 0 && (
                  <Button type="button" variant="outline" size="sm" className="mt-1"
                          onClick={() => applyAiReasons(suggestion)}
                          title={t('Pre-fill the exclusion form with these reasons — you still pick the primary one and confirm')}>
                    {t("Use the AI's exclusion reasons")}
                  </Button>
                )}
                {suggestion.analysis && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-primary">
                      {t('AI analysis')}
                    </summary>
                    <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                      {suggestion.analysis}
                    </p>
                  </details>
                )}
                <p className="mt-1 text-muted-foreground">
                  {t('Suggestion only — your vote is yours.')}
                  {suggestion.cost && (
                    <span title={`${suggestion.cost.model} · ${suggestion.cost.tokens_in} in / ${suggestion.cost.tokens_out} out`}>
                      {' '}{t('· cost {{cost}}', { cost: suggestion.cost.cost_label })}
                    </span>
                  )}
                </p>
              </div>
            )}
            <LiveStatus className="text-xs">{error}</LiveStatus>

            <Button variant="outline" className="w-full"
                    onClick={goPrevious}
                    disabled={myVotes.length === 0 || revisitIndex === myVotes.length - 1}>
              {t('← Previous vote')} {shortcuts && <span className="opacity-60">(P)</span>}
            </Button>

            {criteria.length > 0 && (
              <details className="rounded-md border border-border bg-card p-2">
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                  {t('Eligibility criteria')}
                </summary>
                <ul className="mt-1 max-h-56 space-y-1 overflow-y-auto">
                  {criteria.map((c) => (
                    <li key={c.code} className="text-xs text-muted-foreground" title={c.description}>
                      <span className={cn('font-mono font-medium',
                        c.type === 'include' ? 'text-success' : 'text-destructive')}>
                        {c.code}</span> {c.label}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      )}
      </div>
    </div>
  )
}

function AiSuggestButton({ projectId, recordId, round, onResult, onError }: {
  projectId: number
  recordId: number
  round: number
  onResult: (s: Suggestion) => void
  onError: (e: string) => void
}) {
  const { t } = useTranslation()
  const suggest = useMutation({
    mutationFn: () => api.post<Suggestion>(
      `/api/projects/${projectId}/screening/records/${recordId}/suggest`
      + `?stage=${STAGE}&round=${round}`),
    onSuccess: onResult,
    onError: (e) => onError(e instanceof ApiError ? e.message : t('AI failed')),
  })
  // `blocked`: the stored PDF is over the page limit — never sent to the AI
  const { data: est } = useQuery<{ cost: CostInfo | null; blocked?: string | null }>({
    queryKey: ['ft-ai-estimate', projectId, recordId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/records/${recordId}/ai-estimate`
      + `?stage=${STAGE}&round=${round}`),
  })
  const estTitle = est?.blocked ? est.blocked : est?.cost
    ? t('Estimated cost ≈ {{cost}} ({{model}}), reading the full PDF. Actual cost shown after running.',
        { cost: est.cost.cost_label, model: est.cost.model })
    : undefined
  return (
    <>
      <Button variant="outline" className="w-full" onClick={() => suggest.mutate()}
              disabled={suggest.isPending || !!est?.blocked} title={estTitle}>
        {suggest.isPending ? t('Reading the PDF…')
          : <><Sparkles className="size-3.5 text-primary" />{t('AI suggestion (full text)')}</>}
        {est?.cost && <span className="text-muted-foreground"> · ≈{est.cost.cost_label}</span>}
      </Button>
      {est?.blocked && (
        <p className="text-xs text-muted-foreground">{est.blocked}</p>
      )}
    </>
  )
}

// ---- conflicts ------------------------------------------------------------------

interface ConflictRow {
  id: number
  status: string
  resolution: string
  resolution_note: string
  resolution_reasons: { code: string; label: string }[]
  resolved_by: string | null
  has_pdf: boolean
  record: QueueItem
  votes: { reviewer: string; mine: boolean; decision: string; reasons: string[]
    reason_labels: string[]; justification: string }[]
}

function ConflictsTab({ projectId, round, mode, canResolve }: {
  projectId: number
  round: number
  mode: string
  canResolve: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [view, setView] = useState<'open' | 'resolved'>('open')
  const { data: conflicts = [] } = useQuery<ConflictRow[]>({
    queryKey: ['ftscreen-conflicts', projectId, view, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/conflicts?stage=${STAGE}&status=${view}&round=${round}`),
  })
  const { data: reasonData } = useQuery<{ reasons: ExclusionReason[] }>({
    queryKey: ['ftscreen-reasons', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/screening/reasons?stage=${STAGE}`),
  })
  // the conflict just resolved, kept on screen so a misclick can be undone
  const [lastResolved, setLastResolved] = useState<ResolvedConflict | null>(null)
  useEffect(() => setLastResolved(null), [round])
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['ftscreen-conflicts', projectId] })
    queryClient.invalidateQueries({ queryKey: ['ftscreen-stats', projectId] })
    queryClient.invalidateQueries({ queryKey: ['prisma', projectId] })
  }
  const reopened = () => { setLastResolved(null); invalidate() }
  return (
    <div className="max-w-4xl">
      <div className="mb-4 flex items-center gap-2">
        <Segmented
          value={view}
          onChange={setView}
          options={[
            { value: 'open', label: t('To resolve') },
            { value: 'resolved', label: t('Resolved') },
          ]}
        />
        {!canResolve && (
          <span className="ml-2 text-xs text-muted-foreground">
            {mode === 'arbiter'
              ? t('Arbiter mode: only the arbiters resolve — view only.') : t('View only.')}
          </span>
        )}
      </div>
      {lastResolved && view === 'open' && (
        <JustResolvedBanner projectId={projectId} stage={STAGE} round={round}
                            last={lastResolved} onReopened={reopened}
                            onDismiss={() => setLastResolved(null)} />
      )}
      {conflicts.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {view === 'open' ? t('No conflict to resolve.') : t('No resolved conflict yet.')}
        </p>
      ) : (
        <div className="space-y-4">
          {conflicts.map((c) => (
            <ConflictCard key={c.id} projectId={projectId} round={round} conflict={c}
                          reasons={reasonData?.reasons || []}
                          canResolve={canResolve && view === 'open'}
                          canReopen={canResolve}
                          onResolved={(decision) => {
                            setLastResolved({ id: c.id, title: c.record.title, decision })
                            invalidate()
                          }}
                          onReopened={reopened} />
          ))}
        </div>
      )}
    </div>
  )
}

function ConflictCard({ projectId, round, conflict, reasons, canResolve, canReopen, onResolved, onReopened }: {
  projectId: number
  round: number
  conflict: ConflictRow
  reasons: ExclusionReason[]
  canResolve: boolean
  canReopen: boolean
  onResolved: (decision: string) => void
  onReopened: () => void
}) {
  const { t } = useTranslation()
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [showPdf, setShowPdf] = useState(false)
  const [excluding, setExcluding] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [primary, setPrimary] = useState('')
  const { annotations, create: createAnn, remove: removeAnn } =
    useAnnotations(projectId, showPdf ? conflict.record.id : undefined)

  const resolve = useMutation({
    mutationFn: (payload: { decision: string; reasons: string[] }) =>
      api.post(`/api/projects/${projectId}/screening/conflicts/${conflict.id}/resolve`
        + `?stage=${STAGE}&round=${round}`,
        { decision: payload.decision, reasons: payload.reasons, note }),
    onSuccess: (_data, payload) => onResolved(payload.decision),
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Failed')),
  })
  const toggle = (code: string) => setSelected((prev) => {
    const next = prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    setPrimary((p) => (next.includes(p) ? p : next[0] ?? ''))
    return next
  })
  const chipVariant = (d: string) =>
    d === 'include' ? 'success' : d === 'exclude' ? 'destructive' : 'warning'

  return (
    <Card className="p-4">
      <p className="text-sm font-medium text-foreground">{conflict.record.title}</p>
      <p className="mb-2 text-xs text-muted-foreground">
        {conflict.record.year ?? ''} {conflict.record.journal}
      </p>
      <TagChips projectId={projectId} recordId={conflict.record.id}
                className="mb-2" />
      <div className="mb-3 space-y-1">
        {conflict.votes.map((v, i) => (
          <p key={i} className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            <Badge variant={chipVariant(v.decision)}>
              {v.reviewer}{v.mine ? ` (${t('you')})` : ''}: {t(v.decision)}
            </Badge>
            {v.reason_labels.length > 0 && (
              <span className="text-muted-foreground">[{v.reason_labels.join(', ')}] </span>
            )}
            {v.justification && (
              <span className="italic text-muted-foreground">“{v.justification}”</span>
            )}
          </p>
        ))}
      </div>

      {conflict.has_pdf && (
        <button onClick={() => setShowPdf((v) => !v)}
                className="mb-2 text-xs text-primary hover:underline">
          {showPdf ? t('▾ Hide PDF & highlights') : t('▸ Open PDF & shared highlights')}
        </button>
      )}
      {showPdf && (
        <div className="mb-3 rounded-lg border border-border" style={{ height: '60vh' }}>
          <PdfViewer
            fileUrl={`/api/projects/${projectId}/fulltext/records/${conflict.record.id}/file`}
            annotations={annotations}
            onCreate={(a) => createAnn.mutate(a)}
            onDelete={(id) => removeAnn.mutate(id)} />
        </div>
      )}

      {conflict.status === 'resolved' ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          <p className="min-w-0 flex-1">
            {t('Resolved:')} <span className={cn('font-medium',
              conflict.resolution === 'include' ? 'text-success' : 'text-destructive')}>
              {t(conflict.resolution)}</span>
            {conflict.resolution_reasons.length > 0
              && ` — ${conflict.resolution_reasons.map((r) => r.label).join(', ')}`}
            {conflict.resolved_by && ` · ${t('by')} ${conflict.resolved_by}`}
            {conflict.resolution_note && ` — “${conflict.resolution_note}”`}
          </p>
          {canReopen && (
            <ReopenConflictButton projectId={projectId} conflictId={conflict.id}
                                  stage={STAGE} round={round} onReopened={onReopened} />
          )}
        </div>
      ) : canResolve ? (
        <div>
          <Input value={note} placeholder={t('Resolution note (optional)')}
                 onChange={(e) => setNote(e.target.value)}
                 className="mb-2 text-xs" />
          {!excluding ? (
            <div className="flex gap-2">
              <Button variant="success" size="sm"
                      onClick={() => resolve.mutate({ decision: 'include', reasons: [] })}
                      disabled={resolve.isPending}>
                {t('Include')}
              </Button>
              <Button variant="destructive" size="sm"
                      onClick={() => setExcluding(true)} disabled={resolve.isPending}>
                {t('Exclude…')}
              </Button>
            </div>
          ) : (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2">
              <p className="mb-1 text-xs font-medium text-destructive">
                {t('Primary (●) + secondary reasons')}
              </p>
              <ul className="max-h-40 space-y-1 overflow-y-auto">
                {reasons.map((r) => {
                  const checked = selected.includes(r.code)
                  return (
                    <li key={r.code} className="flex items-start gap-1.5 text-xs">
                      <Checkbox checked={checked} className="mt-0.5"
                                onCheckedChange={() => toggle(r.code)} />
                      <button type="button" onClick={() => checked && setPrimary(r.code)}
                              title={t('Set as primary reason')}
                              aria-label={t('Set as primary reason')} aria-pressed={primary === r.code}
                              className={cn('mt-0.5 h-3 w-3 shrink-0 rounded-full border',
                                primary === r.code ? 'bg-destructive border-destructive'
                                  : 'border-input', checked ? '' : 'opacity-30')} />
                      <span className={r.kind === 'builtin' ? 'italic text-muted-foreground' : ''}>
                        <span className="font-mono font-medium">{r.code}</span> {r.label}
                      </span>
                    </li>
                  )
                })}
              </ul>
              <div className="mt-2 flex gap-2">
                <Button variant="destructive" size="sm"
                        disabled={!primary || resolve.isPending}
                        onClick={() => resolve.mutate({ decision: 'exclude',
                          reasons: [primary, ...selected.filter((c) => c !== primary)] })}>
                  {t('Confirm exclusion')}
                </Button>
                <Button variant="outline" size="sm"
                        onClick={() => { setExcluding(false); setSelected([]); setPrimary('') }}>
                  {t('Cancel')}
                </Button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs italic text-muted-foreground">{t('Awaiting resolution.')}</p>
      )}
      <LiveStatus className="mt-2 text-xs">{error}</LiveStatus>
    </Card>
  )
}

// ---- dashboard ------------------------------------------------------------------

interface ExcludedRecord {
  id: number
  title: string
  authors: string[]
  year: number | null
  journal: string
  doi: string | null
  has_pdf?: boolean
}

/** One-click DOI copy (dedicated button, next to each listed study). */
function CopyDoiButton({ doi }: { doi: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => {
        navigator.clipboard.writeText(doi).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }}
      title={t('Copy DOI: {{doi}}', { doi })}
      className={cn('h-6 shrink-0 px-1.5 text-xs',
        copied && 'border-success/40 text-success hover:text-success')}>
      {copied ? t('✓ copied') : '⧉ DOI'}
    </Button>
  )
}

interface Stats {
  status: string
  allocation?: string
  lead_user_id?: number | null
  shares?: Share[]
  votes_done?: number
  completed?: number
  included?: number
  excluded?: number
  conflicts_open?: number
  conflicts_resolved?: number
  per_reviewer?: ReviewerStat[]
  agreement?: { method: string | null; kappa: number | null
    percent: number | null; n_records: number; pairs?: PairMatrix[] }
  ft?: { assessed: number; not_retrieved: number
    excluded_by_reason: { code: string; label: string; n: number
      records: ExcludedRecord[] }[]
    included_records: ExcludedRecord[] }
}

function DashboardTab({ projectId, round }: { projectId: number; round: number }) {
  const { t } = useTranslation()
  const openPdf = usePdfWindow()
  const { data: stats } = useQuery<Stats>({
    queryKey: ['ftscreen-stats', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/stats?stage=${STAGE}&round=${round}`),
    refetchOnMount: 'always',
  })
  if (!stats) return <p className="text-muted-foreground">{t('Loading…')}</p>
  if (stats.status === 'unconfigured')
    return <p className="text-sm text-muted-foreground">{t('Full-text screening not configured yet.')}</p>
  const a = stats.agreement
  const ft = stats.ft
  return (
    <div className="max-w-3xl space-y-4">
      <Card className="flex flex-wrap gap-6 p-4">
        <Stat label={t('assessed')} value={ft?.assessed ?? '—'} />
        <Stat label={t('included')} value={stats.included ?? '—'} tone="success" />
        <Stat label={t('excluded (with reason)')}
              value={ft ? ft.excluded_by_reason.reduce((s, r) => s + r.n, 0) : '—'}
              tone="destructive" />
        <Stat label={t('not retrievable')} value={ft?.not_retrieved ?? '—'} />
        <Stat label={t('conflicts to resolve')} value={stats.conflicts_open ?? '—'}
              tone={stats.conflicts_open ? 'warning' : undefined} />
        <Stat
          label={
            <>
              {a?.method === 'cohen' ? "Cohen's κ" : a?.method === 'fleiss' ? "Fleiss' κ" : 'κ'}
              {a?.n_records ? ` (${t('{{count}} reports', { count: a.n_records })})` : ''}
            </>
          }
          value={a?.kappa != null ? a.kappa.toFixed(2) : '—'}
        />
      </Card>

      <ReviewerProgress reviewers={stats.per_reviewer ?? []} showMaybe={false} />
      {stats.allocation === 'lead' && (
        <SharesCard shares={stats.shares ?? []}
                    members={(stats.per_reviewer ?? []).map((r) =>
                      ({ user_id: r.user_id, display_name: r.display_name }))}
                    description={t('The lead reviewer holds every report; the co-reviewers share the corpus. Effective share of the co-reviewers against the declared one, late reports included.')} />
      )}
      <AgreementMatrices title={t('Decision matrix')} unit="reports"
                         pairs={a?.pairs ?? []} hideEmptyMaybe />

      {ft && ft.excluded_by_reason.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-foreground">
            {t('Reports excluded by primary reason')}
          </h3>
          <div className="space-y-1">
            {ft.excluded_by_reason.map((r) => (
              <details key={r.code} className="border-b border-border pb-1 last:border-0">
                <summary className="flex cursor-pointer items-center gap-2 py-1 text-sm">
                  <span className="w-14 font-mono text-xs text-muted-foreground">{r.code}</span>
                  <span className="flex-1 text-foreground">{r.label}</span>
                  <span className="font-medium tabular-nums">{r.n}</span>
                </summary>
                <ul className="space-y-1 pb-2 pl-16">
                  {r.records.map((rec) => (
                    <li key={rec.id} className="text-xs text-muted-foreground">
                      {rec.doi ? (
                        <a href={`https://doi.org/${rec.doi}`} target="_blank" rel="noreferrer"
                           className="text-foreground hover:text-primary hover:underline">
                          {rec.title}
                        </a>
                      ) : <span className="text-foreground">{rec.title}</span>}
                      <span className="text-muted-foreground">
                        {' — '}{rec.authors[0] ?? '?'}{rec.authors.length > 1 ? ' et al.' : ''}
                        {rec.year ? `, ${rec.year}` : ''}
                        {rec.journal ? ` · ${rec.journal}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {t('These feed the PRISMA “reports excluded, with reasons” box.')}
          </p>
        </Card>
      )}

      {ft && ft.included_records.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-foreground">
            {t('Studies included this round ({{count}})', { count: ft.included_records.length })}
          </h3>
          <ul className="space-y-1.5">
            {ft.included_records.map((rec) => (
              <li key={rec.id} className="flex items-start gap-2 text-xs text-muted-foreground">
                <div className="min-w-0 flex-1">
                  {rec.has_pdf ? (
                    <button onClick={() => openPdf({ projectId,
                              recordId: rec.id, title: rec.title })}
                            title={t('Open the PDF in the integrated viewer')}
                            className="text-left text-foreground hover:text-primary hover:underline">
                      📄 {rec.title}
                    </button>
                  ) : rec.doi ? (
                    <a href={`https://doi.org/${rec.doi}`} target="_blank" rel="noreferrer"
                       title={t('No stored PDF — opens the publisher page')}
                       className="text-foreground hover:text-primary hover:underline">
                      {rec.title}
                    </a>
                  ) : <span className="text-foreground">{rec.title}</span>}
                  <span className="text-muted-foreground">
                    {' — '}{rec.authors[0] ?? '?'}{rec.authors.length > 1 ? ' et al.' : ''}
                    {rec.year ? `, ${rec.year}` : ''}
                    {rec.journal ? ` · ${rec.journal}` : ''}
                  </span>
                </div>
                {rec.doi && <CopyDoiButton doi={rec.doi} />}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            {t('These are carried forward (snowballing seeds / extraction).')}
          </p>
        </Card>
      )}
    </div>
  )
}
