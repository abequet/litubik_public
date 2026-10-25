// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useWorkHeartbeat } from '../useWorkHeartbeat'
import { ChevronDown, Pencil, RotateCcw, Sparkles } from 'lucide-react'
import {
  api, ApiError,
  type Concept, type Criterion, type JobInfo, type Project, type ProtocolDetail,
  type ProtocolSummary,
} from '../api'
import { useJobWatcher } from '../useJob'
import TagChips from '../components/TagChips'
import {
  TranslateControl, usePrefetchTranslations, useRecordTranslation,
  type Translations,
} from '../components/RecordTranslation'
import ScreeningList from '../components/ScreeningList'
import {
  AgreementMatrices, ReviewerProgress, type PairMatrix, type ReviewerStat,
} from '../components/ScreeningDashboard'
import {
  LeadSettings, LotPreview, LotSettings, LotsDashboard, SharesCard, evenWeights,
  weightsTotal, type LotRow, type Share,
} from '../components/ScreeningLots'
import { ArbiterPicker, canResolveConflicts } from '../components/ArbiterPicker'
import {
  JustResolvedBanner, ReopenConflictButton, type ResolvedConflict,
} from '../components/ConflictUndo'
import { cn } from '@/lib/utils'
import { useShortcutsEnabled } from '@/lib/shortcuts'
import LiveStatus from '../components/LiveStatus'
import {
  HL_GREEN, HL_NEUTRAL, HL_RED, HL_SEARCH, highlight, type HighlightFamily,
} from '@/lib/highlight'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Slider } from '@/components/ui/slider'
import { Segmented } from '@/components/ui/segmented'
import { Stat } from '@/components/ui/stat'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface ConfigInfo {
  config: {
    id: number
    stage: string
    round: number
    allocation: 'all' | 'dual' | 'single_overlap' | 'lots' | 'lead'
    overlap_pct: number
    conflict_resolution: 'consensus' | 'arbiter'
    ai_enabled: boolean
    ai_triage: 'off' | 'admin' | 'reviewers'
    triage_control_pct: number
    ai_batch: boolean
    ai_reveal: 'always' | 'after_vote'
    reviewer_ids: number[]
    lead_user_id: number | null
    weights: Record<string, number> | null
    lot_size: number
    arbiter_ids: number[] | null
    anonymous: boolean
    status: 'draft' | 'active'
    started_at: string | null
  } | null
  /** anonymous reviewers: the names in every payload are pseudonyms */
  names_hidden: boolean
  members: { user_id: number; display_name: string; role: string;
             registered: boolean }[]
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
  translations?: Translations
}

interface ConflictRow {
  id: number
  status: string
  resolution: string
  resolution_note: string
  resolved_by: string | null
  record: QueueItem
  votes: { reviewer: string; mine: boolean; decision: string; reasons: string[]
    justification: string }[]
}

interface Stats {
  status: string
  conflict_resolution?: string
  allocation?: string
  lead_user_id?: number | null
  lots?: LotRow[]
  shares?: Share[]
  assignments_total?: number
  votes_done?: number
  per_reviewer?: ReviewerStat[]
  completed?: number
  included?: number
  excluded?: number
  conflicts_open?: number
  conflicts_resolved?: number
  auto_excluded?: number
  triage_controls?: TriageControlsSummary
  agreement?: { method: string | null; kappa: number | null
    percent: number | null; n_records: number; pairs?: PairMatrix[]
    maybe_as_include?: boolean }
}

/** GET /screening/triage-controls — the AI triage control sample. Pending
 * controls are only counted (the reviewers must not learn which titles are
 * controls); decided ones come with both verdicts. */
interface TriageControlsSummary {
  total: number
  pending: number
  decided: number
  confirmed: number
  contradicted: number
  agreement_pct: number | null
  pct: number
}

interface TriageControlRow {
  record_id: number
  title: string
  authors: string[]
  year: number | null
  confidence: number | null
  reason: string
  held_by: string
  created_at: string
  human: 'include' | 'exclude' | 'maybe' | 'conflict'
  status: 'confirmed' | 'contradicted'
}

interface TriageControlsReport extends TriageControlsSummary {
  rows: TriageControlRow[]
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

/** GET /records/{id}/suggestion in an after_vote round, before the vote. */
interface WithheldSuggestion {
  suggestion: Suggestion | null
  withheld?: boolean
  available?: boolean
}

interface Suggestion {
  revealed_early?: boolean
  decision: string
  confidence: number
  criteria: { code: string; assessment: string; note?: string }[]
  justification: string
  warning?: string
  analysis?: string
  cost?: CostInfo | null
}

/** Criteria of the most recently validated protocol (eligibility reminder). */
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

type Tab = 'screen' | 'conflicts' | 'dashboard' | 'settings'

export default function ScreeningPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const [tab, setTab] = useState<Tab>('screen')
  useWorkHeartbeat(pid, tab === 'conflicts' ? 'conflicts' : 'ta')
  const [roundChoice, setRoundChoice] = useState<number | null>(null)  // null = latest
  // deep link from the pipeline menu's snowballing sub-steps (?round=N)
  const [searchParams] = useSearchParams()
  const urlRound = searchParams.get('round')
  useEffect(() => {
    if (urlRound) setRoundChoice(Number(urlRound))
  }, [urlRound])
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data: info } = useQuery<ConfigInfo>({
    queryKey: ['screening-config', pid, roundChoice],
    queryFn: () => api.get(`/api/projects/${pid}/screening/config`
      + (roundChoice !== null ? `?round=${roundChoice}` : '')),
  })
  const round = info?.round ?? 1
  const isAdmin = info?.my_role === 'admin'
  const active = info?.config?.status === 'active'

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
        {t('Title/abstract screening')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Double blind is enforced server-side: nobody sees another vote until a record is complete. “Maybe” and disagreements become conflicts.')}
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
          {tab === 'screen' && active && info.config
            && info.config.ai_triage !== 'off'
            && (info.config.ai_triage === 'admin'
              ? isAdmin : info.config.reviewer_ids.includes(info.me)) && (
            <TriagePanel projectId={pid} round={round}
                         mode={info.config.ai_triage as 'admin' | 'reviewers'}
                         controlPct={info.config.triage_control_pct ?? 0} />
          )}
          {tab === 'screen' && (active
            ? <ScreenTab projectId={pid} round={round}
                         aiEnabled={!!info.config?.ai_enabled}
                         aiBatch={!!info.config?.ai_batch}
                     afterVote={info.config?.ai_reveal === 'after_vote'} />
            : <p className="text-sm text-muted-foreground">
                {t('Screening has not been started yet')}
                {isAdmin ? ` ${t('— configure it in the Settings tab.')}` : '.'}
              </p>)}
          {tab === 'conflicts' && (active
            ? <ConflictsTab
                projectId={pid}
                round={round}
                mode={info.config!.conflict_resolution}
                canResolve={canResolveConflicts(info.config!, info.members, info.me, isAdmin)}
              />
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
  const [ai, setAi] = useState(c?.ai_enabled ?? false)
  const [triage, setTriage] = useState(c?.ai_triage ?? 'off')
  const [controlPct, setControlPct] = useState(c?.triage_control_pct ?? 0)
  const [batch, setBatch] = useState(c?.ai_batch ?? false)
  const [afterVote, setAfterVote] = useState(c?.ai_reveal === 'after_vote')
  const [anonymous, setAnonymous] = useState(c?.anonymous ?? false)
  const [reviewers, setReviewers] = useState<number[]>(
    c?.reviewer_ids?.length ? c.reviewer_ids : info.members.map((m) => m.user_id))
  // allocation = lots: shares in %, records per lot
  const [weights, setWeights] = useState<Record<string, number>>(
    c?.weights ?? evenWeights(c?.reviewer_ids?.length ? c.reviewer_ids
      : info.members.map((m) => m.user_id)))
  const [lotSize, setLotSize] = useState(c?.lot_size ?? 100)
  const [arbiters, setArbiters] = useState<number[]>(c?.arbiter_ids ?? [])
  // allocation = lead: the reviewer who screens everything (default: me)
  const [lead, setLead] = useState<number | null>(c?.lead_user_id ?? info.me)
  const [error, setError] = useState('')
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['screening-config', projectId] })
    queryClient.invalidateQueries({ queryKey: ['screening-stats', projectId] })
    queryClient.invalidateQueries({ queryKey: ['screening-queue', projectId] })
  }
  const active = c?.status === 'active'
  const lots = allocation === 'lots'
  const isLead = allocation === 'lead'
  const coReviewers = reviewers.filter((uid) => uid !== lead)
  // lots: shares over the reviewers; lead: over the co-reviewers (a single
  // co-reviewer needs no share)
  const weightsOk = lots
    ? Math.abs(weightsTotal(weights, reviewers) - 100) < 0.05
    : !isLead || coReviewers.length <= 1
      || Math.abs(weightsTotal(weights, coReviewers) - 100) < 0.05
  const leadOk = !isLead || (lead != null && reviewers.includes(lead) && coReviewers.length >= 1)

  const save = useMutation({
    mutationFn: async () => {
      await api.put(`/api/projects/${projectId}/screening/config?round=${round}`, {
        stage: 'ta', allocation, overlap_pct: overlap,
        conflict_resolution: resolution, ai_enabled: ai, ai_triage: triage,
        triage_control_pct: controlPct,
        ai_batch: batch, ai_reveal: afterVote ? 'after_vote' : 'always',
        anonymous,
        reviewer_ids: reviewers, lead_user_id: isLead ? lead : null,
        weights: lots ? Object.fromEntries(
          reviewers.map((uid) => [String(uid), Number(weights[String(uid)]) || 0]))
          : isLead && coReviewers.length > 1 ? Object.fromEntries(
            coReviewers.map((uid) => [String(uid), Number(weights[String(uid)]) || 0]))
          : null,
        lot_size: lotSize, arbiter_ids: resolution === 'arbiter' ? arbiters : [],
      })
    },
    onSuccess: () => { invalidate(); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const start = useMutation({
    mutationFn: async () => {
      await save.mutateAsync()
      return api.post(`/api/projects/${projectId}/screening/start?round=${round}`)
    },
    onSuccess: () => { invalidate(); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Start failed')),
  })
  const reset = useMutation({
    mutationFn: () => api.post(`/api/projects/${projectId}/screening/reset?round=${round}`),
    onSuccess: () => { invalidate(); setError('') },
  })

  const optionRow = 'flex items-center gap-2 text-sm text-muted-foreground'

  return (
    <>
    <Card className="max-w-2xl space-y-4 p-5">
      {active && (
        <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">
          {t('Screening is running (started {{date}}). Reset wipes all votes and conflicts.',
             { date: new Date(c!.started_at!).toLocaleString() })}
        </p>
      )}
      <div>
        <p className="mb-1.5 text-sm font-medium text-foreground">{t('Who screens what')}</p>
        <RadioGroup value={allocation} disabled={active}
                    onValueChange={(v) => setAllocation(v as typeof allocation)}
                    className="gap-1.5">
          {([
            ['all', t('Everyone screens every record (kappa on the full set)')],
            ['dual', t('Two reviewers per record, spread across the team (Covidence-style)')],
            ['single_overlap', t('One reviewer per record + a % double-screened for the kappa')],
            ['lots', t('Weighted lots — two reviewers per lot, pairs rotate, each reviewer takes a declared share of the work')],
            ['lead', t('Lead reviewer — one reviewer screens every record, the others share the corpus (equal or declared shares)')],
          ] as const).map(([value, label]) => (
            <label key={value} className={optionRow}>
              <RadioGroupItem value={value} />
              {label}
              {value === 'single_overlap' && allocation === 'single_overlap' && (
                <Input type="number" min={0} max={100} value={overlap}
                       disabled={active}
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
        {lots && (
          <div className="mt-2">
            <LotSettings members={info.members} reviewers={reviewers}
                         weights={weights} onWeights={setWeights}
                         lotSize={lotSize} onLotSize={setLotSize}
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
                         onArbiters={setArbiters} disabled={active} lots={lots} />
        )}
      </div>
      <div>
        <p className="mb-1.5 text-sm font-medium text-foreground">
          {t('Reviewers')} ({reviewers.length})
        </p>
        <div className="flex flex-col gap-1.5">
          {info.members.map((m) => (
            <label key={m.user_id} className={optionRow}>
              <Checkbox disabled={active}
                        checked={reviewers.includes(m.user_id)}
                        onCheckedChange={(v) => setReviewers(v
                          ? [...reviewers, m.user_id]
                          : reviewers.filter((id) => id !== m.user_id))} />
              {m.display_name} <span className="text-xs text-muted-foreground/70">({m.role})</span>
              {m.registered === false && (
                <span
                  className="rounded-full bg-warning/15 px-1.5 text-xs font-medium text-warning"
                  title={t('Added by e-mail — they will claim this account (and its votes) by registering with that address')}
                >
                  {t('awaiting registration')}
                </span>
              )}
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
        {t('AI suggestions on click (needs a validated protocol and an API key)')}
      </label>
      <label className={cn(optionRow, 'ml-6 items-start')}>
        <Checkbox disabled={!ai} checked={batch} className="mt-0.5"
                  onCheckedChange={(v) => {
                    setBatch(!!v)
                    if (active)
                      api.put(`/api/projects/${projectId}/screening/config/ai-batch?round=${round}`,
                              { ai_batch: !!v }).then(invalidate)
                  }} />
        <span>
          {t('Batch AI suggestion')}
          <span className="text-muted-foreground/70">
            {' '}{t('— adds a button on the screen page so each reviewer can pre-run the title/abstract AI suggestion on all their remaining records at once (changeable while the round runs)')}
          </span>
        </span>
      </label>
      <label className={cn(optionRow, 'ml-6 items-start')}>
        <Checkbox disabled={!ai} checked={afterVote} className="mt-0.5"
                  onCheckedChange={(v) => {
                    setAfterVote(!!v)
                    if (active)
                      api.put(`/api/projects/${projectId}/screening/config/ai-reveal?round=${round}`,
                              { ai_reveal: v ? 'after_vote' : 'always' }).then(invalidate)
                  }} />
        <span>
          {t('Show the AI suggestion only after the vote')}
          <span className="text-muted-foreground/70">
            {' '}{t('— enforced server-side: a reviewer sees the suggestion once their own vote is cast. A suggestion already computed in batch can still be revealed on purpose with a dedicated button; that choice is recorded in the AI-use journal (changeable while the round runs)')}
          </span>
        </span>
      </label>
      <div>
        <p className="mb-1.5 text-sm font-medium text-foreground">
          {t('AI title triage')}
          <span className="font-normal text-muted-foreground/70">
            {' '}{t('— bulk exclusion proposals from titles only, always validated by a human (changeable while the round runs)')}
          </span>
        </p>
        <RadioGroup value={triage} className="gap-1.5"
                    onValueChange={(v) => {
                      setTriage(v as typeof triage)
                      if (active)
                        api.put(`/api/projects/${projectId}/screening/config/triage-mode?round=${round}`,
                                { ai_triage: v }).then(invalidate)
                    }}>
          {([
            ['off', t('Off')],
            ['admin', t('Admin only — the validated list excludes the papers globally (bypasses the two-reviewer vote, audited)')],
            ['reviewers', t("Each reviewer — the validated list casts the reviewer's own exclude votes (double screening kept)")],
          ] as const).map(([value, label]) => (
            <label key={value} className={optionRow}>
              <RadioGroupItem value={value} />
              {label}
            </label>
          ))}
        </RadioGroup>
        <TriageControlSetting pct={controlPct} disabled={triage === 'off'}
          onChange={(next) => {
            setControlPct(next)
            if (active)
              api.put(`/api/projects/${projectId}/screening/config/triage-mode?round=${round}`,
                      { ai_triage: triage, triage_control_pct: next }).then(invalidate)
          }} />
      </div>
      <p className="text-xs text-muted-foreground">
        {t('{{count}} unique record(s) will enter screening.', { count: info.eligible_records })}
        {' '}{t('Agreement statistic with {{count}} reviewer(s):', { count: reviewers.length })}{' '}
        <span className="font-medium text-foreground">
          {reviewers.length >= 3 ? "Fleiss' κ" : "Cohen's κ"}
        </span>
        {allocation === 'all'
          ? t(', computed on all records.')
          : t(', computed on the double-screened records.')}
      </p>
      <div className="flex gap-2">
        {!active && (
          <>
            <Button variant="outline" onClick={() => save.mutate()}
                    disabled={save.isPending || !weightsOk}>
              {t('Save')}
            </Button>
            {!lots && (
              <Button onClick={() => start.mutate()}
                      disabled={start.isPending || reviewers.length === 0 || !leadOk || !weightsOk}>
                {t('Start screening')}
              </Button>
            )}
          </>
        )}
        {active && (
          <Button
            variant="outline"
            className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => {
              if (confirm(t('Reset title/abstract screening round {{round}}? Its {{count}} vote(s) and all its conflict resolutions will be deleted.',
                            { round, count: info.n_votes })))
                reset.mutate()
            }}
          >
            {t('Reset screening')}
          </Button>
        )}
      </div>
      {!active && lots && reviewers.length >= 2 && weightsOk && (
        <LotPreview projectId={projectId} round={round} members={info.members}
                    saveConfig={() => save.mutateAsync()}
                    onStarted={() => { invalidate(); setError('') }} />
      )}
      <LiveStatus className="text-sm">{error}</LiveStatus>
    </Card>
    {active && lots && (
      <p className="mt-2 max-w-2xl text-xs text-muted-foreground">
        {t('The lots, their pairs and their progress are on the Dashboard tab, with the allocation CSV.')}
      </p>
    )}
    <HighlightSettings projectId={projectId} />
    </>
  )
}

/** Control sample of the AI title triage: a checkbox plus the share held
 * back (1–50 %, 10 % by default). Changeable while the round runs. */
function TriageControlSetting({ pct, disabled, onChange }: {
  pct: number
  disabled: boolean
  onChange: (pct: number) => void
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(String(pct || 10))
  useEffect(() => { if (pct > 0) setDraft(String(pct)) }, [pct])
  const commit = () => {
    const n = Math.min(50, Math.max(1, Math.round(Number(draft)) || 10))
    setDraft(String(n))
    if (n !== pct) onChange(n)
  }
  return (
    <div className={cn('ml-6 mt-1.5 flex items-start gap-2 text-sm text-muted-foreground',
                        disabled && 'opacity-60')}>
      <Checkbox checked={pct > 0} className="mt-0.5" disabled={disabled}
                onCheckedChange={(v) => onChange(v ? 10 : 0)} />
      <span>
        {t('Control sample of the triage')}
        {pct > 0 && !disabled && (
          <>
            {' '}
            <Input type="number" min={1} max={50} value={draft}
                   onChange={(e) => setDraft(e.target.value)} onBlur={commit}
                   onKeyDown={(e) => { if (e.key === 'Enter') commit() }}
                   aria-label={t('Control sample share (%)')}
                   className="inline-block h-6 w-16 px-1.5 text-xs tabular-nums" />
            {' %'}
          </>
        )}
        <span className="text-muted-foreground/70">
          {' '}{t('— this share of every exclusion list you validate is held back at random and stays in the human queue, unmarked; the dashboard then checks that the reviewers exclude those titles too (changeable while the round runs)')}
        </span>
      </span>
    </div>
  )
}

// ---- highlight word lists (T14) -----------------------------------------------------

export function HighlightSettings({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [green, setGreen] = useState('')
  const [red, setRed] = useState('')
  const [saved, setSaved] = useState(false)
  const { data } = useQuery<{ green: string[]; red: string[] }>({
    queryKey: ['highlights', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/highlights`),
  })
  useEffect(() => {
    if (data) {
      setGreen(data.green.join('\n'))
      setRed(data.red.join('\n'))
    }
  }, [data])
  const toList = (s: string) =>
    s.split(/[\n,;]+/).map((w) => w.trim()).filter(Boolean)
  const save = useMutation({
    mutationFn: () => api.put(`/api/projects/${projectId}/highlights`,
      { green: toList(green), red: toList(red) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['highlights', projectId] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
  })
  return (
    <Card className="mt-4 max-w-2xl space-y-3 p-5">
      <div>
        <p className="text-sm font-medium text-foreground">
          {t('Highlighted words in titles & abstracts')}
        </p>
        <p className="text-xs text-muted-foreground">
          {t("On top of the equations' keywords (neutral), these two hand-curated lists are highlighted in")}{' '}
          <mark className={HL_GREEN}>{t('green')}</mark> {t('and')}{' '}
          <mark className={HL_RED}>{t('red')}</mark>{' '}
          {t('on the screening screens. One word or phrase per line.')}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-muted-foreground">
          <span className="mb-1 block font-medium text-success">{t('Green — speaks for inclusion')}</span>
          <Textarea value={green} onChange={(e) => setGreen(e.target.value)}
                    rows={6} placeholder={t('driving simulator\nrandomized')}
                    className="text-xs" />
        </label>
        <label className="text-xs text-muted-foreground">
          <span className="mb-1 block font-medium text-destructive">{t('Red — speaks for exclusion')}</span>
          <Textarea value={red} onChange={(e) => setRed(e.target.value)}
                    rows={6} placeholder={t('animal model\nprotocol only')}
                    className="text-xs" />
        </label>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => save.mutate()}
                disabled={save.isPending}>
          {t('Save word lists')}
        </Button>
        {saved && <span className="text-xs text-success">{t('✓ Saved')}</span>}
      </div>
    </Card>
  )
}

// ---- AI title triage ---------------------------------------------------------------

interface TriageProposal {
  record_id: number
  title: string
  year: number | null
  author: string
  confidence: number
  reason: string
}

interface TriageLatest {
  proposals: TriageProposal[] | null
  n_screened?: number
  threshold?: number
  generated_at?: string
  job_id?: number
}

/** Some imported titles are web-scraped blobs (whole poster-session lists,
 * bibliographies, HTML entities) rather than a real title. Decode the common
 * entities, collapse whitespace and cap the length so the proposal list stays
 * readable — the full string is still available in the hover tooltip. */
function cleanTitle(raw: string): string {
  const text = (raw || '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ').trim()
  return text.length > 180 ? text.slice(0, 180) + '…' : text
}

/** Bulk pre-screening on titles only: the AI proposes exclusions above the
 * confidence threshold, the human unticks anything uncertain and validates. */
function TriagePanel({ projectId, round, mode, controlPct }: {
  projectId: number
  round: number
  mode: 'admin' | 'reviewers'
  controlPct: number
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [threshold, setThreshold] = useState(95)
  const [allProposals, setAllProposals] = useState<TriageProposal[] | null>(null)
  const [screened, setScreened] = useState(0)
  const [generatedAt, setGeneratedAt] = useState<string | null>(null)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [message, setMessage] = useState('')
  const [open, setOpen] = useState(true)
  const jobIdRef = useRef<number | null>(null)
  const initedThreshold = useRef(false)

  const latest = useQuery<TriageLatest>({
    queryKey: ['triage-latest', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/triage/latest?round=${round}`),
  })
  useEffect(() => {
    const d = latest.data
    if (!d || !d.proposals) return
    setAllProposals(d.proposals)
    setScreened(d.n_screened ?? 0)
    setGeneratedAt(d.generated_at ?? null)
    if (!initedThreshold.current && typeof d.threshold === 'number') {
      setThreshold(d.threshold)
      initedThreshold.current = true
    }
  }, [latest.data])

  const visible = useMemo(
    () => (allProposals ?? [])
      .filter((p) => Math.round(p.confidence * 100) >= threshold),
    [allProposals, threshold])

  useEffect(() => {
    setChecked(new Set(visible.map((p) => p.record_id)))
  }, [visible])

  const watcher = useJobWatcher(async () => {
    if (jobIdRef.current === null) return
    try {
      const job = await api.get<JobInfo>(`/api/jobs/${jobIdRef.current}`)
      if (job.status !== 'done') return
      const result = job.result as { proposals: TriageProposal[]
        n_screened: number }
      setAllProposals(result.proposals)
      setScreened(result.n_screened)
      setGeneratedAt(new Date().toISOString())
      setOpen(true)
      queryClient.invalidateQueries({ queryKey: ['triage-latest', projectId, round] })
      setMessage(result.proposals.length === 0
        ? t('The AI found nothing to exclude among the {{count}} unvoted titles.',
            { count: result.n_screened }) : '')
    } catch { setMessage(t('Could not fetch the proposals')) }
  })

  const run = async () => {
    setMessage('')
    try {
      const est = await api.get<{ candidates: number; cost?: CostInfo }>(
        `/api/projects/${projectId}/screening/triage/estimate?round=${round}`)
      const cost = est.cost?.cost_label
      if (!window.confirm(
        t('Send {{count}} unvoted title(s) to the AI for triage', { count: est.candidates })
        + (cost ? ` (≈ ${cost})` : '')
        + '?\n\n' + t('These are proposals only — nothing is excluded until the checklist is validated.'))) return
      const r = await api.post<{ job_id: number; candidates: number }>(
        `/api/projects/${projectId}/screening/triage?round=${round}`,
        { threshold })
      jobIdRef.current = r.job_id
      watcher.watch(r.job_id)
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : t('Could not start the triage'))
    }
  }

  const apply = useMutation({
    mutationFn: () => api.post<{ applied: number; skipped: number; controls: number }>(
      `/api/projects/${projectId}/screening/triage/apply?round=${round}`,
      { record_ids: [...checked] }),
    onSuccess: (r) => {
      setAllProposals((prev) => prev
        ? prev.filter((p) => !checked.has(p.record_id)) : prev)
      setMessage('✓ ' + (mode === 'admin'
        ? t('{{count}} paper(s) excluded', { count: r.applied })
        : t('{{count}} paper(s) voted exclude by you', { count: r.applied }))
        + (r.controls
          ? ' — ' + t('{{count}} held back as control sample (left in the queue, unmarked)', { count: r.controls })
          : '')
        + (r.skipped
          ? ' — ' + t('{{count}} skipped (voted meanwhile)', { count: r.skipped })
          : '') + '.')
      for (const k of ['screening-queue', 'screening-stats', 'screening-config'])
        queryClient.invalidateQueries({ queryKey: [k, projectId] })
      queryClient.invalidateQueries({ queryKey: ['project-progress', projectId] })
      queryClient.invalidateQueries({ queryKey: ['prisma', projectId] })
      queryClient.invalidateQueries({ queryKey: ['triage-latest', projectId, round] })
    },
    onError: (e) => setMessage(e instanceof ApiError ? e.message : t('Apply failed')),
  })

  const toggle = (id: number) => setChecked((s) => {
    const next = new Set(s)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const hasProposals = allProposals !== null && allProposals.length > 0

  return (
    <Card className="mb-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-60 flex-1 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">
            <Sparkles className="mr-1 inline size-3.5 text-primary" />{t('AI title triage')}
          </span>
          {' '}{t('— sends the unvoted titles to the AI, which proposes the clearly off-topic ones for exclusion. Proposals are saved: come back to validate them later, or move the threshold to refine the list without re-running the AI.')}
        </p>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          {t('confidence ≥')}
          <Slider min={70} max={99} value={[threshold]} className="w-28"
                  onValueChange={([v]) => setThreshold(v)} />
          <span className="w-8 font-medium tabular-nums text-foreground">{threshold}%</span>
        </label>
        <Button size="sm" onClick={run} disabled={!!watcher.state}>
          {watcher.state ? t('Screening titles…')
            : hasProposals ? t('Re-run') : t('Propose exclusions')}
        </Button>
      </div>
      {watcher.state && (
        <p className="mt-1 text-xs text-muted-foreground">{watcher.state}</p>
      )}
      {(message || watcher.error) && (
        <p className={cn('mt-1 text-xs',
          message.startsWith('✓') ? 'text-success' : 'text-muted-foreground')}>
          {message || watcher.error}
        </p>
      )}

      {hasProposals && (
        <div className="mt-3 rounded-md border border-border">
          <button onClick={() => setOpen((o) => !o)}
                  className="flex w-full items-center gap-2 px-4 py-2 text-left">
            <span className="text-sm font-semibold text-foreground">
              {t('{{count}} saved exclusion proposal(s)', { count: visible.length })}
            </span>
            <span className="text-xs font-normal text-muted-foreground">
              {t('≥{{threshold}}% · {{kept}} kept from {{screened}} titles',
                 { threshold, kept: allProposals!.length, screened })}
              {generatedAt ? ` · ${new Date(generatedAt).toLocaleString()}` : ''}
            </span>
            <ChevronDown className={cn('ml-auto size-4 text-muted-foreground transition-transform',
              open && 'rotate-180')} />
          </button>
          {open && (
            <>
              <div className="flex items-center gap-2 px-4 pb-2 text-xs">
                <span className="text-muted-foreground">
                  {t('Untick anything uncertain — it stays in the normal queue. Nothing is written until you validate.')}
                  {controlPct > 0 && (
                    <> {t('Control sample: {{pct}} % of what you validate is held back at random and left in the queue, unmarked.', { pct: controlPct })}</>
                  )}
                </span>
                <button onClick={() => setChecked(new Set(visible.map((p) => p.record_id)))}
                        className="ml-auto text-primary hover:underline">{t('select all')}</button>
                <button onClick={() => setChecked(new Set())}
                        className="text-primary hover:underline">{t('none')}</button>
              </div>
              <ul className="max-h-96 divide-y divide-border overflow-y-auto border-t border-border px-4">
                {visible.map((p) => (
                  <li key={p.record_id} className="flex items-start gap-2.5 py-2">
                    <Checkbox checked={checked.has(p.record_id)}
                              onCheckedChange={() => toggle(p.record_id)} className="mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 break-words text-sm leading-snug text-foreground"
                         title={p.title}>{cleanTitle(p.title)}</p>
                      <p className="text-xs text-muted-foreground">
                        {p.author || '?'}{p.year ? ` · ${p.year}` : ''}
                        {' — '}{p.reason}
                      </p>
                    </div>
                    <Badge variant="outline" className="shrink-0" title={t('AI self-assessed confidence')}>
                      {(p.confidence * 100).toFixed(0)}%
                    </Badge>
                  </li>
                ))}
                {visible.length === 0 && (
                  <li className="py-3 text-xs text-muted-foreground">
                    {t('No proposal at ≥{{threshold}}% — lower the threshold to see more of the {{count}} saved.',
                       { threshold, count: allProposals!.length })}
                  </li>
                )}
              </ul>
              <div className="flex items-center gap-3 rounded-b-md border-t border-border bg-muted/50 px-4 py-3">
                <p className="flex-1 text-xs text-muted-foreground">
                  {t('{{count}} selected', { count: checked.size })}
                  {mode === 'admin'
                    ? ` ${t('— validated papers are excluded from the round (audited as "AI title triage").')}`
                    : ` ${t('— validated papers receive YOUR exclude vote (the other reviewer still screens them).')}`}
                </p>
                <Button variant="destructive" size="sm" onClick={() => apply.mutate()}
                        disabled={checked.size === 0 || apply.isPending}>
                  {mode === 'admin'
                    ? t('Exclude {{count}} paper(s)', { count: checked.size })
                    : t('Cast {{count}} exclude vote(s)', { count: checked.size })}
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  )
}

// ---- screen tab -------------------------------------------------------------------

function ScreenTab({ projectId, round, aiEnabled, aiBatch, afterVote }: {
  projectId: number
  round: number
  aiEnabled: boolean
  aiBatch: boolean
  afterVote: boolean
}) {
  const { t } = useTranslation()
  const shortcuts = useShortcutsEnabled()
  const queryClient = useQueryClient()
  const { data: queue } = useQuery<{ total: number; done: number
    skipped: number; items: (QueueItem & { skipped?: boolean })[] }>({
    queryKey: ['screening-queue', projectId, round],
    queryFn: () => api.get(
      // the first is on screen; the next three feed the translation prefetch
      `/api/projects/${projectId}/screening/queue?limit=4&round=${round}`),
  })
  const { data: concepts = [] } = useQuery<Concept[]>({
    queryKey: ['concepts', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/concepts`),
  })
  const criteria = useValidatedCriteria(projectId)
  const keywords = useMemo(() => concepts.flatMap((c) => c.keywords), [concepts])
  // T14: hand-curated red/green lists on top of the equations' keywords
  const { data: hl } = useQuery<{ green: string[]; red: string[] }>({
    queryKey: ['highlights', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/highlights`),
  })
  const families = useMemo<HighlightFamily[]>(() => [
    { words: hl?.red ?? [], className: HL_RED },
    { words: hl?.green ?? [], className: HL_GREEN },
    { words: keywords, className: HL_NEUTRAL },
  ], [hl, keywords])

  interface HistoryEntry {
    record: QueueItem
    decision: string
    note: string
    locked: boolean
  }
  const { data: myVotes = [] } = useQuery<HistoryEntry[]>({
    queryKey: ['screening-my-votes', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/my-votes?round=${round}`),
  })
  const [showHistory, setShowHistory] = useState(false)
  // ticket #8: single-record view (default) vs infinite-scroll list view;
  // typing in the search box always lands in the list
  const [view, setView] = useState<'single' | 'list'>(
    () => (localStorage.getItem('litubik-screen-view') === 'list' ? 'list' : 'single'))
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')  // debounced
  useEffect(() => {
    const id = setTimeout(() => setQuery(search.trim()), 250)
    return () => clearTimeout(id)
  }, [search])
  const listMode = view === 'list' || query !== ''
  const switchView = (v: 'single' | 'list') => {
    setView(v)
    localStorage.setItem('litubik-screen-view', v)
    if (v === 'single') { setSearch(''); setQuery('') }
  }
  const listFamilies = useMemo<HighlightFamily[]>(() => (query
    ? [{ words: query.split(/\s+/), className: HL_SEARCH }, ...families]
    : families), [query, families])
  const [revisitIndex, setRevisitIndex] = useState<number | null>(null)
  const revisit = revisitIndex !== null ? myVotes[revisitIndex] ?? null : null
  const record = revisit?.record ?? queue?.items[0]
  // AI reading aid: title + abstract in the interface language, on request or
  // automatically — the original stays the text that is edited and screened
  const translation = useRecordTranslation({
    projectId, recordId: record?.id ?? 0,
    translations: record?.translations, autoAllowed: !!record,
  })
  // automatic mode translates the next records while this one is being read
  usePrefetchTranslations(projectId, queue?.items.slice(1, 4) ?? [])

  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  // T21: double-click edits the displayed abstract (traced server-side)
  const [editingAbstract, setEditingAbstract] = useState(false)
  const [abstractDraft, setAbstractDraft] = useState('')
  useEffect(() => setEditingAbstract(false), [record?.id])
  const saveAbstract = useMutation({
    mutationFn: () => api.put(
      `/api/projects/${projectId}/records/${record!.id}/abstract`,
      { abstract: abstractDraft }),
    onSuccess: () => {
      setEditingAbstract(false)
      queryClient.invalidateQueries({ queryKey: ['screening-queue', projectId] })
      queryClient.invalidateQueries({ queryKey: ['screening-my-votes', projectId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  // what the server lets this reviewer see for the record on screen: the
  // cached suggestion (batch rounds), or — in an after_vote round — only
  // whether there is one to reveal
  const showCached = aiEnabled && (aiBatch || afterVote)
  const { data: cached } = useQuery<WithheldSuggestion>({
    queryKey: ['screening-suggestion', projectId, record?.id, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/records/${record!.id}/suggestion`
      + `?round=${round}`),
    enabled: showCached && record !== undefined,
  })
  useEffect(() => {
    if (showCached) setSuggestion(cached?.suggestion ?? null)
  }, [cached, record?.id, showCached])
  // the suggestion stays hidden until I vote, unless I ask to see it first
  const withheld = afterVote && !revisit && !!cached?.withheld
  const reveal = useMutation({
    mutationFn: () => api.post<{ suggestion: Suggestion }>(
      `/api/projects/${projectId}/screening/records/${record!.id}/reveal?round=${round}`),
    onSuccess: (r) => {
      setSuggestion(r.suggestion)
      queryClient.invalidateQueries({ queryKey: ['screening-suggestion', projectId, record?.id] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('AI failed')),
  })
  // after_vote: once voted, the suggestion I could not see is shown next to
  // my decision before the queue moves on
  const [postVote, setPostVote] = useState<{
    title: string; decision: string; suggestion: Suggestion } | null>(null)

  const [batchMsg, setBatchMsg] = useState('')
  const batchJobId = useRef<number | null>(null)
  const batchWatcher = useJobWatcher(async () => {
    queryClient.invalidateQueries({ queryKey: ['screening-suggestion', projectId] })
    queryClient.invalidateQueries({ queryKey: ['ai-batch-estimate', projectId] })
    if (batchJobId.current === null) return
    try {
      const job = await api.get<JobInfo>(`/api/jobs/${batchJobId.current}`)
      if (job.status !== 'done') return
      const res = job.result as { generated?: number; failed?: number }
      setBatchMsg('✓ ' + t('{{count}} AI suggestion(s) ready', { count: res.generated ?? 0 })
        + ((res.failed ?? 0) > 0 ? ' — ' + t('{{count}} failed', { count: res.failed }) : '')
        + '. ' + t('They show under each article as you screen.'))
    } catch { /* the watcher surfaces failures via its own error */ }
  })
  const { data: batchEst } = useQuery<{
    n_to_generate: number; already_suggested: number; cost?: CostInfo }>({
    queryKey: ['ai-batch-estimate', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/ai-batch/estimate?round=${round}`),
    enabled: aiEnabled && aiBatch,
  })
  const runBatch = async () => {
    const n = batchEst?.n_to_generate ?? 0
    const cost = batchEst?.cost?.cost_label
    if (!window.confirm(
      t('Generate AI title/abstract suggestions for your {{count}} remaining record(s)', { count: n })
      + (cost ? ` (≈ ${cost})` : '')
      + '?\n\n' + t('These are proposals only — nothing is voted for you.'))) return
    setBatchMsg('')
    try {
      const r = await api.post<{ job_id: number; n: number }>(
        `/api/projects/${projectId}/screening/ai-batch?round=${round}`)
      batchJobId.current = r.job_id
      batchWatcher.watch(r.job_id)
    } catch (e) {
      setBatchMsg(e instanceof ApiError ? e.message : t('Could not start the batch'))
    }
  }

  const vote = useMutation({
    mutationFn: async (decision: string) => {
      const voted = record!
      await api.post(`/api/projects/${projectId}/screening/vote?round=${round}`,
        { record_id: voted.id, decision, justification: note })
      if (afterVote && aiEnabled && !revisit && !suggestion) {
        // blind vote cast: show what the AI had said, if anything
        try {
          const r = await api.get<WithheldSuggestion>(
            `/api/projects/${projectId}/screening/records/${voted.id}/suggestion?round=${round}`)
          if (r.suggestion) setPostVote({ title: voted.title, decision, suggestion: r.suggestion })
        } catch { /* the comparison card is a courtesy, never a blocker */ }
      }
    },
    onSuccess: () => {
      setRevisitIndex(null)
      setSuggestion(null)
      setNote('')
      setError('')
      queryClient.invalidateQueries({ queryKey: ['screening-suggestion', projectId] })
      queryClient.invalidateQueries({ queryKey: ['screening-queue', projectId] })
      queryClient.invalidateQueries({ queryKey: ['screening-my-votes', projectId] })
      queryClient.invalidateQueries({ queryKey: ['screening-stats', projectId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Vote failed')),
  })

  const skip = useMutation({
    mutationFn: () =>
      api.post(`/api/projects/${projectId}/screening/skip?round=${round}`,
        { record_id: record!.id }),
    onSuccess: () => {
      setSuggestion(null)
      setNote('')
      setError('')
      queryClient.invalidateQueries({ queryKey: ['screening-queue', projectId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Skip failed')),
  })

  const openRevisit = (index: number) => {
    const entry = myVotes[index]
    if (!entry) return
    setRevisitIndex(index)
    setNote(entry.note)
    setSuggestion(null)
    setError('')
  }

  const goPrevious = () => {
    if (myVotes.length === 0) return
    const next = revisitIndex === null ? 0 : revisitIndex + 1
    if (next >= myVotes.length) return
    openRevisit(next)
  }

  const resumeQueue = () => {
    if (revisitIndex === null) return
    setRevisitIndex(null)
    setNote('')
    setSuggestion(null)
    setError('')
  }

  const canVote = record !== undefined && !(revisit?.locked)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (listMode) return  // list cards are voted with the mouse
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
      if (e.key === 'Escape') resumeQueue()
      if (!shortcuts) return  // WCAG 2.1.4: single-letter keys switched off ("?" menu)
      if (e.key === 'p') goPrevious()
      if (!canVote) return
      if (e.key === 'y' || e.key === 'i') vote.mutate('include')
      if (e.key === 'n' || e.key === 'x') vote.mutate('exclude')
      if (e.key === 'm') vote.mutate('maybe')
      if (e.key === 's' && !revisit) skip.mutate()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [record?.id, vote.isPending, myVotes.length, revisitIndex, canVote, listMode, postVote, shortcuts])  // eslint-disable-line

  if (!queue) return <p className="text-muted-foreground">{t('Loading queue…')}</p>
  const pct = queue.total ? Math.round((queue.done / queue.total) * 100) : 0

  return (
    <div className="max-w-5xl">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented
          value={listMode ? 'list' : 'single'}
          onChange={switchView}
          options={[
            { value: 'single', label: t('One by one') },
            { value: 'list', label: t('List') },
          ]}
        />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('Search my papers…')}
          className="h-8 w-40 sm:w-56"
          title={t('Keyword search on title, abstract, authors and journal — results open in the list view')}
        />
        {!listMode && (
          <Button variant={showHistory ? 'default' : 'secondary'} size="sm"
                  className="rounded-full"
                  onClick={() => setShowHistory((v) => !v)}>
            {showHistory ? t('◂ History') : `${t('History')} (${myVotes.length})`}
          </Button>
        )}
        <Progress value={pct} className="min-w-24 flex-1" />
        <span className="text-xs tabular-nums text-muted-foreground">
          {queue.done}/{queue.total}
          {queue.skipped > 0 && (
            <span className="text-warning"> · {t('{{count}} skipped', { count: queue.skipped })}</span>
          )}
        </span>
      </div>
      {listMode ? (
        <ScreeningList projectId={projectId} round={round}
                       families={listFamilies} query={query} />
      ) : (
      <>
      {!revisit && record && (record as { skipped?: boolean }).skipped && (
        <p className="mb-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-1.5 text-xs text-warning">
          {t("⏭ You skipped this record earlier — it's back for a decision.")}
        </p>
      )}

      <div className={showHistory ? 'grid items-start gap-4 lg:grid-cols-[17rem_1fr]' : undefined}>
      {showHistory && (
        <Card className="max-h-[70vh] overflow-y-auto p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            {t('Already screened ({{count}}) — click to revisit', { count: myVotes.length })}
          </p>
          {myVotes.length === 0 && (
            <p className="text-xs text-muted-foreground">{t('Nothing yet.')}</p>
          )}
          <ul className="space-y-1">
            {myVotes.map((entry, i) => (
              <li key={entry.record.id}>
                <button
                  onClick={() => openRevisit(i)}
                  className={cn('w-full rounded-md border px-2 py-1.5 text-left text-xs',
                    revisitIndex === i
                      ? 'border-border bg-accent'
                      : 'border-transparent hover:bg-accent')}
                >
                  <span className={cn('inline-block w-14 font-medium',
                    entry.decision === 'include' ? 'text-success'
                      : entry.decision === 'exclude' ? 'text-destructive'
                      : 'text-warning')}>
                    {t(entry.decision)}
                  </span>
                  {entry.locked && <span title={t('Record completed — read-only')}>🔒 </span>}
                  <span className="text-muted-foreground">
                    {entry.record.title.slice(0, 60)}
                    {entry.record.title.length > 60 ? '…' : ''}
                  </span>
                  {entry.record.year && (
                    <span className="text-muted-foreground"> ({entry.record.year})</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {postVote && (
        <Card className="mb-4 border-l-2 border-l-primary p-4 text-sm" aria-live="polite">
          <p className="text-xs text-muted-foreground">{postVote.title}</p>
          <p className="mt-1 font-medium text-foreground">
            {t('You voted {{yours}} · the AI had suggested {{ai}} (confidence {{pct}} %)', {
              yours: t(postVote.decision), ai: t(postVote.suggestion.decision),
              pct: (postVote.suggestion.confidence * 100).toFixed(0) })}
          </p>
          {postVote.suggestion.justification && (
            <p className="mt-1 text-muted-foreground">{postVote.suggestion.justification}</p>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            {t('Your vote stands as cast. Shown afterwards so the suggestion could not anchor it.')}
          </p>
          <Button size="sm" className="mt-2" onClick={() => setPostVote(null)}>
            {t('Next')} <span className="opacity-60">(Enter)</span>
          </Button>
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
        <div className="grid items-start gap-4 lg:grid-cols-[1fr_15rem]">
          {/* record content */}
          <Card className="p-5">
            {revisit && (
              <div className={cn('mb-3 flex items-center gap-2 rounded-md px-3 py-2 text-xs',
                revisit.locked
                  ? 'bg-muted text-muted-foreground'
                  : 'bg-warning/10 text-warning')}>
                <span className="flex-1">
                  {revisit.locked ? (
                    <>{t('Completed record — you voted “{{decision}}”', { decision: t(revisit.decision) })}
                      {revisit.note && <> {t('with note “{{note}}”', { note: revisit.note })}</>}.{' '}
                      {t('Read-only (see the Conflicts tab if it needs arbitration).')}</>
                  ) : (
                    <>{t('Revisiting a previous vote — you voted “{{decision}}”', { decision: t(revisit.decision) })}
                      {revisit.note && <> {t('with note “{{note}}”', { note: revisit.note })}</>}.{' '}
                      {t('Vote again to change it, or resume without changing anything.')}</>
                  )}
                </span>
                <button onClick={resumeQueue}
                        className="shrink-0 rounded-md border border-current/30 px-2 py-1 font-medium hover:bg-background/50">
                  {t('Resume queue →')} <span className="opacity-60">(Esc)</span>
                </button>
              </div>
            )}
            <h2 className="mb-1 font-semibold text-foreground">
              {highlight(translation.shown?.title || record.title, families)}
            </h2>
            <p className="mb-2 text-xs text-muted-foreground">
              {record.authors.slice(0, 6).join('; ')}{record.authors.length > 6 ? '…' : ''}
              {record.year ? ` · ${record.year}` : ''}
              {record.journal ? ` · ${record.journal}` : ''}
              {record.doi && (
                <>
                  {' · '}
                  <a href={`https://doi.org/${record.doi}`} target="_blank" rel="noreferrer"
                     className="font-mono text-primary hover:underline">{record.doi}</a>
                </>
              )}
            </p>
            <TagChips projectId={projectId} recordId={record.id} className="mb-3" />
            {!editingAbstract && (
              <TranslateControl control={translation.control} className="mb-2" />
            )}
            {editingAbstract ? (
              <div>
                <Textarea value={abstractDraft} autoFocus rows={10}
                          onChange={(e) => setAbstractDraft(e.target.value)}
                          className="text-sm" />
                <div className="mt-2 flex items-center gap-2">
                  <Button size="sm" onClick={() => saveAbstract.mutate()}
                          disabled={saveAbstract.isPending}>
                    {t('Save abstract')}
                  </Button>
                  <Button size="sm" variant="ghost"
                          onClick={() => setEditingAbstract(false)}>
                    {t('Cancel')}
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    {t("Edits are logged (author & time) and the imported text is kept — the abstract is the screening's source data.")}
                  </span>
                </div>
              </div>
            ) : record.abstract ? (
              <div>
                <p className="text-sm leading-relaxed text-foreground/90">
                  {highlight(translation.shown?.abstract || record.abstract, families)}
                </p>
                {/* keyboard-reachable replacement for the former double-click */}
                <Button variant="ghost" size="sm"
                        onClick={() => {
                          setAbstractDraft(record.abstract)
                          setEditingAbstract(true)
                        }}
                        title={t('Edit the original abstract (the change is logged)')}
                        className="mt-1 h-6 gap-1 px-1.5 text-xs text-muted-foreground">
                  <Pencil className="size-3" aria-hidden /> {t('Edit the abstract')}
                </Button>
              </div>
            ) : (
              <AbstractPaste projectId={projectId} recordId={record.id} />
            )}
            {withheld && !suggestion && (
              <div className="mt-4 rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
                <Sparkles className="mr-1 inline size-3.5 text-primary" />
                {cached?.available
                  ? t('An AI suggestion exists for this record. In this round it is shown after your vote.')
                  : t('In this round the AI suggestion is shown after your vote.')}
                {cached?.available && (
                  <Button type="button" variant="outline" size="sm" className="ml-2"
                          onClick={() => reveal.mutate()} disabled={reveal.isPending}
                          title={t('Looking before you vote is allowed, and recorded in the AI-use journal so blind votes can be told apart.')}>
                    {reveal.isPending ? '…' : t('See the AI suggestion before voting')}
                  </Button>
                )}
              </div>
            )}
            {suggestion && (
              <div className="mt-4 rounded-md border border-border border-l-2 border-l-primary bg-accent p-3 text-sm">
                {suggestion.revealed_early && (
                  <p className="mb-1 text-xs text-warning">
                    {t('Revealed before your vote — recorded in the AI-use journal.')}
                  </p>
                )}
                <p className="font-medium text-foreground">
                  <Sparkles className="mr-1 inline size-3.5 text-primary" />
                  {t('AI suggests:')} {t(suggestion.decision)}
                  <span
                    className="cursor-help font-normal text-muted-foreground"
                    title={t('Self-assessed by the model: its own probability that a careful human reviewer would reach the same decision. Not calibrated — treat as a rough signal.')}
                  >
                    {' '}{t('(confidence {{pct}} %ⓘ)', { pct: (suggestion.confidence * 100).toFixed(0) })}
                  </span>
                </p>
                {suggestion.warning && (
                  <p className="mt-1 rounded bg-warning/15 px-2 py-1 text-xs text-warning">
                    ⚠ {suggestion.warning}
                  </p>
                )}
                <p className="mt-1 text-muted-foreground">{suggestion.justification}</p>
                {suggestion.criteria.length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {suggestion.criteria.map((c) =>
                      `${c.code}: ${c.assessment}`).join(' · ')}
                  </p>
                )}
                {suggestion.analysis && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-primary">
                      {t("Show the AI's step-by-step analysis")}
                    </summary>
                    <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
                      {suggestion.analysis}
                    </p>
                  </details>
                )}
                <div className="mt-2 flex items-center gap-2">
                  <p className="flex-1 text-xs text-muted-foreground">
                    {t('Suggestion only — your vote is yours.')}
                    {suggestion.cost && (
                      <span title={`${suggestion.cost.model} · ${suggestion.cost.tokens_in} in / ${suggestion.cost.tokens_out} out`}>
                        {' '}{t('· cost {{cost}}', { cost: suggestion.cost.cost_label })}
                      </span>
                    )}
                  </p>
                  {(!afterVote || !!revisit) && (
                    <AiSuggestButton projectId={projectId} recordId={record.id}
                                     round={round}
                                     onResult={setSuggestion} onError={setError}
                                     force compact />
                  )}
                </div>
              </div>
            )}
            <LiveStatus className="mt-2 text-sm">{error}</LiveStatus>
          </Card>

          {/* fixed action rail */}
          <div className="sticky top-4 space-y-2">
            <Button variant="success" className="w-full"
                    onClick={() => vote.mutate('include')}
                    disabled={vote.isPending || !canVote}>
              {t('Include')} {shortcuts && <span className="opacity-60">(Y)</span>}
            </Button>
            <Button variant="warning" className="w-full"
                    onClick={() => vote.mutate('maybe')}
                    disabled={vote.isPending || !canVote}>
              {t('Maybe')} {shortcuts && <span className="opacity-60">(M)</span>}
            </Button>
            <Button variant="destructive" className="w-full"
                    onClick={() => vote.mutate('exclude')}
                    disabled={vote.isPending || !canVote}>
              {t('Exclude')} {shortcuts && <span className="opacity-60">(N)</span>}
            </Button>
            {!revisit && (
              <Button variant="outline" className="w-full"
                      onClick={() => skip.mutate()}
                      disabled={skip.isPending || vote.isPending || !canVote}
                      title={t('No decision now — the record moves to the back of your queue and comes around again')}>
                {t('⏭ Skip — decide later')} {shortcuts && <span className="opacity-60">(S)</span>}
              </Button>
            )}
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t('Note for this vote (visible during conflict resolution)…')}
              rows={3}
              className="text-xs"
            />
            {aiEnabled && (!afterVote || !!revisit) && (
              <AiSuggestButton projectId={projectId} recordId={record.id}
                               round={round}
                               onResult={setSuggestion} onError={setError} />
            )}
            {aiEnabled && aiBatch && (
              <div className="space-y-1">
                <Button variant="outline" className="w-full"
                        onClick={runBatch}
                        disabled={!!batchWatcher.state
                          || (batchEst?.n_to_generate ?? 0) === 0}
                        title={t('Run the title/abstract AI suggestion on every record you still have to vote on, in one go — each result then appears under its article.')}>
                  {batchWatcher.state ? t('AI-screening your queue…')
                    : <><Sparkles className="size-3.5 text-primary" />{t('Batch AI — my {{count}} remaining', { count: batchEst?.n_to_generate ?? 0 })}</>}
                  {!batchWatcher.state && batchEst?.cost && (
                    <span className="text-muted-foreground">
                      {' '}· ≈{batchEst.cost.cost_label}</span>
                  )}
                </Button>
                {batchWatcher.state && (
                  <p className="text-xs text-muted-foreground">{batchWatcher.state}</p>
                )}
                {(batchMsg || batchWatcher.error) && (
                  <p className={cn('text-xs',
                    batchMsg.startsWith('✓') ? 'text-success' : 'text-muted-foreground')}>
                    {batchWatcher.error || batchMsg}
                  </p>
                )}
              </div>
            )}
            <Button variant="outline" className="w-full"
                    onClick={goPrevious}
                    disabled={myVotes.length === 0
                      || revisitIndex === myVotes.length - 1}>
              {t('← Previous vote')} {shortcuts && <span className="opacity-60">(P)</span>}
            </Button>
            {criteria.length > 0 && (
              <details className="rounded-md border border-border bg-card p-2" open>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                  {t('Eligibility criteria')}
                </summary>
                <ul className="mt-1 max-h-64 space-y-1 overflow-y-auto">
                  {criteria.map((c) => (
                    <li key={c.code} className="text-xs text-muted-foreground"
                        title={c.description}>
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
      </>
      )}
    </div>
  )
}

function AbstractPaste({ projectId, recordId }: { projectId: number; recordId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const save = useMutation({
    mutationFn: () => api.put(
      `/api/projects/${projectId}/records/${recordId}/abstract`,
      { abstract: text }),
    onSuccess: () => {
      setText('')
      queryClient.invalidateQueries({ queryKey: ['screening-queue', projectId] })
      queryClient.invalidateQueries({ queryKey: ['records', projectId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  return (
    <div className="rounded-md border border-dashed border-border p-3">
      <p className="mb-2 text-xs text-muted-foreground">
        {t('No abstract in the metadata — paste it here (it attaches to the record for everyone).')}
      </p>
      <Textarea
        value={text} rows={4}
        onChange={(e) => setText(e.target.value)}
        placeholder={t('Paste the abstract…')}
      />
      <Button variant="outline" size="sm" className="mt-1"
              onClick={() => save.mutate()} disabled={!text.trim() || save.isPending}>
        {t('Save abstract')}
      </Button>
      <LiveStatus className="mt-1 text-xs">{error}</LiveStatus>
    </div>
  )
}

function AiSuggestButton({ projectId, recordId, round, stage, onResult, onError, force, compact }: {
  projectId: number
  recordId: number
  round: number
  stage?: string
  onResult: (s: Suggestion) => void
  onError: (e: string) => void
  force?: boolean
  compact?: boolean
}) {
  const { t } = useTranslation()
  const suggest = useMutation({
    mutationFn: () => api.post<Suggestion>(
      `/api/projects/${projectId}/screening/records/${recordId}/suggest`
      + `?round=${round}` + (stage ? `&stage=${stage}` : '') + (force ? '&force=true' : '')),
    onSuccess: onResult,
    onError: (e) => onError(e instanceof ApiError ? e.message : t('AI failed')),
  })
  const { data: est } = useQuery<{ cost: CostInfo | null }>({
    queryKey: ['ai-estimate', projectId, recordId, round, stage ?? 'ta'],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/records/${recordId}/ai-estimate`
      + `?round=${round}` + (stage ? `&stage=${stage}` : '')),
  })
  const estTitle = est?.cost
    ? t('Estimated cost ≈ {{cost}} ({{model}}). Actual cost shown after running.',
        { cost: est.cost.cost_label, model: est.cost.model })
    : undefined
  if (compact) {
    return (
      <Button variant="outline" size="sm" onClick={() => suggest.mutate()} disabled={suggest.isPending}
              title={t('Discard the cached suggestion and ask the model again (new LLM call)')}>
        {suggest.isPending ? '…' : <><RotateCcw className="size-3.5" />{t('Regenerate')}</>}
      </Button>
    )
  }
  return (
    <Button variant="outline" className="w-full" onClick={() => suggest.mutate()}
            disabled={suggest.isPending} title={estTitle}>
      {suggest.isPending ? t('Asking AI…') : <><Sparkles className="size-3.5 text-primary" />{t('AI suggestion')}</>}
      {est?.cost && <span className="text-muted-foreground"> · ≈{est.cost.cost_label}</span>}
    </Button>
  )
}

// ---- conflicts -------------------------------------------------------------------

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
    queryKey: ['screening-conflicts', projectId, view, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/conflicts?status=${view}&round=${round}`),
  })
  // the conflict just resolved, kept on screen so a misclick can be undone
  const [lastResolved, setLastResolved] = useState<ResolvedConflict | null>(null)
  useEffect(() => setLastResolved(null), [round])
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['screening-conflicts', projectId] })
    queryClient.invalidateQueries({ queryKey: ['screening-stats', projectId] })
    queryClient.invalidateQueries({ queryKey: ['prisma', projectId] })
  }
  const reopened = () => { setLastResolved(null); invalidate() }
  return (
    <div className="max-w-3xl">
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
              ? t('Arbiter mode: only the arbiters resolve — view only.')
              : t('View only.')}
          </span>
        )}
      </div>
      {lastResolved && view === 'open' && (
        <JustResolvedBanner projectId={projectId} stage="ta" round={round}
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

function ConflictCard({ projectId, round, conflict, canResolve, canReopen, onResolved, onReopened }: {
  projectId: number
  round: number
  conflict: ConflictRow
  canResolve: boolean
  canReopen: boolean
  onResolved: (decision: string) => void
  onReopened: () => void
}) {
  const { t } = useTranslation()
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const resolve = useMutation({
    mutationFn: (decision: 'include' | 'exclude') =>
      api.post(`/api/projects/${projectId}/screening/conflicts/${conflict.id}/resolve?round=${round}`,
        { decision, note }),
    onSuccess: (_data, decision) => onResolved(decision),
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Failed')),
  })
  const chipVariant = (d: string) =>
    d === 'include' ? 'success' : d === 'exclude' ? 'destructive' : 'warning'

  return (
    <Card className="p-4">
      <p className="text-sm font-medium text-foreground">{conflict.record.title}</p>
      <p className="mb-2 text-xs text-muted-foreground">
        {conflict.record.year ?? ''} {conflict.record.journal}
      </p>
      {/* tags stay attachable while arbitrating — the "keep for the
          manuscript" shelf matters most right before an exclusion */}
      <TagChips projectId={projectId} recordId={conflict.record.id}
                className="mb-2" />
      <div className="mb-3 space-y-1">
        {conflict.votes.map((v, i) => (
          <p key={i} className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            <Badge variant={chipVariant(v.decision)}>
              {v.reviewer}{v.mine ? ` (${t('you')})` : ''}: {t(v.decision)}
            </Badge>
            {v.justification && (
              <span className="italic text-muted-foreground">“{v.justification}”</span>
            )}
          </p>
        ))}
      </div>
      {conflict.record.abstract && (
        <div className="mb-3">
          <p className={cn('text-xs leading-relaxed text-muted-foreground',
               !expanded && 'line-clamp-3')}>
            {conflict.record.abstract}
          </p>
          <button type="button" aria-expanded={expanded}
                  onClick={() => setExpanded((v) => !v)}
                  className="mt-0.5 text-xs text-muted-foreground hover:text-foreground hover:underline">
            {expanded ? t('Show less') : t('Show the full abstract')}
          </button>
        </div>
      )}
      {conflict.status === 'resolved' ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          <p className="min-w-0 flex-1">
            {t('Resolved:')} <span className={cn('font-medium',
              conflict.resolution === 'include' ? 'text-success' : 'text-destructive')}>
              {t(conflict.resolution)}</span>
            {conflict.resolved_by && ` ${t('by')} ${conflict.resolved_by}`}
            {conflict.resolution_note && ` — “${conflict.resolution_note}”`}
          </p>
          {canReopen && (
            <ReopenConflictButton projectId={projectId} conflictId={conflict.id}
                                  stage="ta" round={round} onReopened={onReopened} />
          )}
        </div>
      ) : canResolve ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={note} placeholder={t('Resolution note (optional)')}
            onChange={(e) => setNote(e.target.value)}
            className="min-w-40 flex-1"
          />
          <Button variant="success" size="sm" onClick={() => resolve.mutate('include')}
                  disabled={resolve.isPending}>
            {t('Include')}
          </Button>
          <Button variant="destructive" size="sm" onClick={() => resolve.mutate('exclude')}
                  disabled={resolve.isPending}>
            {t('Exclude')}
          </Button>
        </div>
      ) : (
        <p className="text-xs italic text-muted-foreground">{t('Awaiting resolution.')}</p>
      )}
      <LiveStatus className="mt-2 text-xs">{error}</LiveStatus>
    </Card>
  )
}

// ---- dashboard -------------------------------------------------------------------

interface AutoExcludedRow {
  record_id: number
  title: string
  authors: string[]
  year: number | null
  round: number
  kind: 'exclusion' | 'vote'
  validated_by: string
  validated_at: string
  reason: string
}

function DashboardTab({ projectId, round }: { projectId: number; round: number }) {
  const { t } = useTranslation()
  const { data: stats } = useQuery<Stats>({
    queryKey: ['screening-stats', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/stats?round=${round}`),
    refetchOnMount: 'always',
  })
  const { data: autoExcluded = [] } = useQuery<AutoExcludedRow[]>({
    queryKey: ['auto-excluded', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/auto-excluded?round=${round}`),
  })
  // admin-only in admin mode (403 for a reviewer: the card simply stays hidden)
  const { data: controls } = useQuery<TriageControlsReport>({
    queryKey: ['triage-controls', projectId, round],
    queryFn: () => api.get(
      `/api/projects/${projectId}/screening/triage-controls?round=${round}`),
    enabled: !!stats?.triage_controls?.total,
    retry: false,
  })
  if (!stats) return <p className="text-muted-foreground">{t('Loading…')}</p>
  if (stats.status === 'unconfigured') {
    return <p className="text-sm text-muted-foreground">{t('Screening not configured yet.')}</p>
  }
  const agreement = stats.agreement
  return (
    <div className="max-w-3xl space-y-4">
      <Card className="flex flex-wrap gap-6 p-4">
        <Stat label={t('votes cast')} value={stats.votes_done ?? '—'} />
        <Stat label={t('records decided')} value={stats.completed ?? '—'} />
        <Stat label={t('included')} value={stats.included ?? '—'} tone="success" />
        <Stat label={t('excluded')} value={stats.excluded ?? '—'} tone="destructive" />
        <Stat label={t('conflicts to resolve')} value={stats.conflicts_open ?? '—'}
              tone={stats.conflicts_open ? 'warning' : undefined} />
        <Stat label={t('conflicts resolved')} value={stats.conflicts_resolved ?? '—'} />
        {!!stats.auto_excluded && (
          <Stat label={t('AI title triage')} value={stats.auto_excluded} tone="destructive" />
        )}
        {!!stats.triage_controls?.total && (
          <Stat label={t('triage controls')}
                value={`${stats.triage_controls.confirmed}/${stats.triage_controls.decided}`}
                tone={stats.triage_controls.contradicted ? 'warning' : undefined} />
        )}
        <Stat
          label={
            <>
              {agreement?.method === 'cohen' ? "Cohen's κ"
                : agreement?.method === 'fleiss' ? "Fleiss' κ" : 'κ'}
              {agreement?.n_records
                ? ` (${t('{{count}} records', { count: agreement.n_records })}` : ''}
              {agreement?.percent != null
                ? `, ${t('{{pct}} % raw agreement', { pct: (agreement.percent * 100).toFixed(0) })})` :
                agreement?.n_records ? ')' : ''}
            </>
          }
          value={agreement?.kappa != null ? agreement.kappa.toFixed(2) : '—'}
        />
      </Card>
      {agreement?.kappa != null && agreement.kappa < 0.2 && (
        <p className="-mt-2 text-xs text-muted-foreground">
          {t('A low or negative κ despite high raw agreement is expected when almost all votes fall in one category (prevalence paradox): chance agreement is then very high, so κ measures little beyond it.')}
        </p>
      )}
      <ReviewerProgress reviewers={stats.per_reviewer ?? []} showMaybe />
      {stats.allocation === 'lead' && (
        <SharesCard shares={stats.shares ?? []}
                    members={(stats.per_reviewer ?? []).map((r) =>
                      ({ user_id: r.user_id, display_name: r.display_name }))}
                    description={t('The lead reviewer holds every record; the co-reviewers share the corpus. Effective share of the co-reviewers against the declared one, late records included.')} />
      )}
      {stats.allocation === 'lots' && (
        <LotsDashboard projectId={projectId} round={round} stage="ta"
                       lots={stats.lots ?? []} shares={stats.shares ?? []}
                       members={(stats.per_reviewer ?? []).map((r) =>
                         ({ user_id: r.user_id, display_name: r.display_name }))} />
      )}
      <AgreementMatrices title={t('Vote cross-matrix')} unit="records"
                         pairs={agreement?.pairs ?? []}
                         maybeAsInclude={agreement?.maybe_as_include} />
      {controls && controls.total > 0 && <TriageControlsCard report={controls} />}
      {autoExcluded.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-1 text-sm font-semibold text-foreground">
            {t('Papers excluded via AI title triage ({{count}})', { count: autoExcluded.length })}
          </h3>
          <p className="mb-3 text-xs text-muted-foreground">
            {t("Permanent audit trail (#13) — every AI-proposed exclusion that a human validated, with the AI's reason. “Global exclusion” = admin validation; “reviewer vote” = one reviewer's own validated vote.")}
          </p>
          <ul className="max-h-80 divide-y divide-border overflow-y-auto">
            {autoExcluded.map((r) => (
              <li key={`${r.kind}-${r.record_id}-${r.validated_by}`} className="py-2">
                <p className="text-xs leading-snug text-foreground">{r.title}</p>
                <p className="text-xs text-muted-foreground">
                  {r.authors[0] ?? '?'}{r.authors.length > 1 ? ' et al.' : ''}
                  {r.year ? ` · ${r.year}` : ''}
                  {r.reason && <> — <span className="italic">{r.reason}</span></>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {r.kind === 'exclusion' ? t('Global exclusion') : t('Reviewer vote')}
                  {' · '}{t('validated by')}{' '}{r.validated_by}
                  {r.validated_at
                    ? ` · ${new Date(r.validated_at).toLocaleString()}` : ''}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

/** Dashboard card: does the human screening confirm the AI title triage?
 * Shows the sample's tally and the decided controls only. */
function TriageControlsCard({ report }: { report: TriageControlsReport }) {
  const { t } = useTranslation()
  const HUMAN: Record<TriageControlRow['human'], string> = {
    include: t('included'), exclude: t('excluded'), maybe: t('maybe'),
    conflict: t('conflict'),
  }
  const worrying = report.decided > 0 && report.contradicted / report.decided > 0.1
  return (
    <Card className="p-4">
      <h3 className="mb-1 text-sm font-semibold text-foreground">
        {t('AI triage control sample ({{count}})', { count: report.total })}
      </h3>
      <p className="mb-3 text-xs text-muted-foreground">
        {t('{{pct}} % of every validated exclusion list was held back at random and left in the queue, unmarked. Once the reviewers rule on a control, their decision is compared with the AI\'s: an exclusion confirms the triage, anything else contradicts it.', { pct: report.pct })}
      </p>
      <div className="mb-3 flex flex-wrap gap-6">
        <Stat label={t('still in the queue')} value={report.pending} />
        <Stat label={t('confirmed (excluded by hand)')} value={report.confirmed} tone="success" />
        <Stat label={t('contradicted (kept by hand)')} value={report.contradicted}
              tone={report.contradicted ? 'destructive' : undefined} />
        <Stat label={t('agreement')}
              value={report.agreement_pct != null ? `${report.agreement_pct} %` : '—'} />
      </div>
      {worrying && (
        <p className="mb-3 text-xs text-warning">
          {t('The reviewers kept {{count}} of the {{decided}} decided controls — the confidence threshold or the validated lists deserve a second look before trusting the automatic exclusions.',
             { count: report.contradicted, decided: report.decided })}
        </p>
      )}
      {report.rows.length > 0 && (
        <ul className="max-h-80 divide-y divide-border overflow-y-auto">
          {report.rows.map((r) => (
            <li key={r.record_id} className="py-2">
              <p className="text-xs leading-snug text-foreground">{r.title}</p>
              <p className="text-xs text-muted-foreground">
                {r.authors[0] ?? '?'}{r.authors.length > 1 ? ' et al.' : ''}
                {r.year ? ` · ${r.year}` : ''}
                {r.reason && <> — <span className="italic">{r.reason}</span></>}
              </p>
              <p className="text-xs">
                <span className={r.status === 'confirmed' ? 'text-success' : 'text-destructive'}>
                  {r.status === 'confirmed' ? t('Confirmed') : t('Contradicted')}
                </span>
                <span className="text-muted-foreground">
                  {' · '}{t('AI: exclude')}{r.confidence != null ? ` (${Math.round(r.confidence * 100)} %)` : ''}
                  {' · '}{t('reviewers: {{decision}}', { decision: HUMAN[r.human] })}
                  {' · '}{t('held back by')}{' '}{r.held_by}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
