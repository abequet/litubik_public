// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useWorkHeartbeat } from '../useWorkHeartbeat'
import { Check, Sparkles } from 'lucide-react'
import { api, ApiError, type Project } from '../api'
import { usePdfWindow } from '../components/PdfWindow'
import { cn } from '@/lib/utils'
import LiveStatus from '../components/LiveStatus'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import ConsensusPanel from '@/components/appraisal/ConsensusPanel'

const API = (pid: number) => `/api/projects/${pid}/extraction`

/** Radix Select forbids empty-string values — this sentinel stands in for the
 * "no value / clear" option and is mapped back to '' before hitting the API. */
const NO_VALUE = '__none__'

/** Fetch a per-article AI cost estimate lazily (only once the button is
 * hovered) so a big table doesn't fire one request per row up front. */
function useHoverEstimate(pid: number, recordId: number, kind: string) {
  const [on, setOn] = useState(false)
  const { data } = useQuery<{ cost: CostInfo | null; blocked?: string | null }>({
    queryKey: ['ext-ai-estimate', pid, recordId, kind],
    queryFn: () => api.get(
      `${API(pid)}/records/${recordId}/ai-estimate?kind=${kind}`),
    enabled: on,
  })
  // `blocked`: the stored PDF is over the page limit — never sent to the AI
  return { cost: data?.cost ?? null, blocked: data?.blocked ?? null,
           onMouseEnter: () => setOn(true) }
}

interface Column {
  id: number
  name: string
  col_type: 'text' | 'number' | 'bool' | 'choice' | 'multi'
  description: string
  options: string[]
  position: number
}

/** A starter column set. `is_default` is the one this project's review type
 * suggests; the others stay pickable. */
interface TemplateInfo {
  key: string
  label: string
  description: string
  n_columns: number
  is_default: boolean
}

interface Cell {
  user_id: number | null
  value: unknown
  origin: 'ai' | 'human'
  validated: boolean
}

interface CostInfo {
  cost_label: string
  cost_usd: number
  model: string
  tokens_in: number
  tokens_out: number
  estimated: boolean
}

/** One study reported by an article (chantier 9). Every article has at least
 * one; the design, the cells and the appraisal state belong to the study. */
interface StudyBlock {
  study_id: number
  uuid: string
  label: string
  position: number
  study_design: string | null
  design_origin: string | null
  cells: Record<string, Cell[]>
  jbi: { mine_done: boolean; n_appraisals: number; scores: JbiScore[] }
}
interface Row {
  record_id: number
  title: string
  doi: string | null
  authors: string[]
  year: number | null
  journal: string
  study_design: string | null
  design_origin: string | null
  assigned_to: number[]
  assigned_to_me: boolean
  has_pdf: boolean
  cells: Record<string, Cell[]>
  jbi: { mine_done: boolean; n_appraisals: number; scores: JbiScore[] }
  studies: StudyBlock[]
}

interface JbiScore {
  user_id: number
  overall: string
  n_yes: number
  n_questions: number
  n_answered: number
}

/** What the instrument's answers mean — read from the server so no page
 * names an instrument: whether an overall judgement exists and whether the
 * count of criteria met is a figure worth showing (MMAT says no to both). */
interface InstrumentSummary {
  key: string
  label: string
  citation: string
  url: string
  builtin: boolean
  overall: boolean
  score: boolean
}

/** "8/13" per assessor (criteria met) when the instrument scores; otherwise
 * how far the appraisal got ("5/7 answered"). A partial one is flagged ~. */
function jbiScoreLabel(scores: JbiScore[], scored: boolean): string {
  return scores.map((s) => scored
    ? `${s.n_answered < s.n_questions ? '~' : ''}${s.n_yes}/${s.n_questions}`
    : `${s.n_answered}/${s.n_questions}`)
    .join(' · ')
}

interface TableData {
  config: { n_extractors: number; extractor_ids: number[]; status: string } | null
  columns: Column[]
  rows: Row[]
  instrument: InstrumentSummary
}

interface ConfigInfo {
  config: { n_extractors: number; extractor_ids: number[]; status: string
    started_at: string | null } | null
  members: { user_id: number; display_name: string; role: string }[]
  eligible_records: number
  me: number
  my_role: string
}

interface Checklist {
  key: string
  label: string
  options: string[]
  // how an instrument spells a stored answer (MMAT: unclear -> "Can't tell")
  option_labels?: Record<string, string>
  domains: { label: string; optional?: boolean
             questions: { id: string; text: string }[] }[]
}

/** The label of an answer button, in the instrument's own words. */
function answerLabel(checklist: Checklist, option: string): string {
  return checklist.option_labels?.[option] ?? (option === 'na' ? 'N/A' : option)
}

/** A criterion number as the instrument prints it: JBI's q7 is "7.", MMAT's
 * own ids (S1, 1.3, 5.5) are shown as they are. */
function criterionNumber(id: string): string {
  return id.replace(/^q(\d+)$/, '$1')
}

export default function ExtractionPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  type Tab = 'table' | 'jbi' | 'consensus' | 'settings'
  // deep links from the Results KPI tiles (…/extraction?tab=jbi)
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>(
    searchParams.get('tab') === 'jbi' ? 'jbi' : 'table')
  useWorkHeartbeat(pid, tab === 'jbi' || tab === 'consensus' ? 'appraisal' : 'extraction')
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data: info } = useQuery<ConfigInfo>({
    queryKey: ['extraction-config', pid],
    queryFn: () => api.get(`${API(pid)}/config`),
  })
  const isAdmin = info?.my_role === 'admin'
  const active = info?.config?.status === 'active'
  const { data: appraisalConfig } = useQuery<{ dual: boolean }>({
    queryKey: ['appraisal-config', pid],
    queryFn: () => api.get(`/api/projects/${pid}/appraisal/config`),
  })
  const dualAppraisal = appraisalConfig?.dual ?? false

  useEffect(() => {
    if (info && !active && isAdmin) setTab('settings')
  }, [info?.config?.status])  // eslint-disable-line

  const tabs: { id: Tab; label: string }[] = [
    { id: 'table', label: t('Table') },
    { id: 'jbi', label: t('Critical appraisal') },
    // only worth a tab when two assessors can actually disagree
    ...(dualAppraisal ? [{ id: 'consensus' as Tab, label: t('Disagreements') }] : []),
    ...(isAdmin ? [{ id: 'settings' as Tab, label: t('Settings') }] : []),
  ]

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Data extraction')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-3xl text-sm text-muted-foreground">
        {t("Extract the evidence table from the final included studies. Cells filled by the AI stay amber until a human validates them; with double extraction each extractor has their own cells, compared side by side. Qualify each study's design to open the matching appraisal checklist.")}
      </p>
      <div className="mb-4 flex items-center justify-between gap-2">
        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex-1">
          <TabsList>
            {tabs.map((t) => (
              <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="flex shrink-0 gap-2">
          <Button asChild variant="outline" size="sm">
            <a href={`${API(pid)}/export.csv`}>⬇ CSV</a>
          </Button>
          <Button asChild variant="outline" size="sm">
            <a href={`${API(pid)}/export.xlsx`}>⬇ XLSX</a>
          </Button>
        </div>
      </div>
      {tab === 'table' && <TableTab pid={pid} me={info?.me ?? 0} />}
      {tab === 'jbi' && <JbiTab pid={pid} />}
      {tab === 'consensus' && <ConsensusPanel pid={pid} />}
      {tab === 'settings' && isAdmin && info && (
        <SettingsTab pid={pid} info={info} />
      )}
    </div>
  )
}

// ---- Table tab --------------------------------------------------------------------

/** The shared design vocabulary (services/appraisal/instruments.py DESIGNS),
 * abbreviated for table headers. A design exists whether or not the project's
 * instrument has a checklist for it. */
export const DESIGN_LABELS: Record<string, string> = {
  rct: 'RCT', quasi_experimental: 'Quasi-exp.', cohort: 'Cohort',
  case_control: 'Case-control', cross_sectional: 'Cross-sect.',
  qualitative: 'Qualitative', case_report: 'Case report',
  systematic_review: 'Syst. review', mixed_methods: 'Mixed methods',
  other: 'Other',
}

function TableTab({ pid, me }: { pid: number; me: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery<TableData>({
    queryKey: ['extraction-table', pid],
    queryFn: () => api.get(`${API(pid)}/table`),
  })
  const [onlyMine, setOnlyMine] = useState(false)
  const openPdf = usePdfWindow()
  const [error, setError] = useState('')
  const [lastCost, setLastCost] = useState<CostInfo | null>(null)
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['extraction-table', pid] })

  const prefill = useMutation({
    mutationFn: (recordId: number) =>
      api.post<{ written: number; skipped_human: number; cost?: CostInfo }>(
        `${API(pid)}/records/${recordId}/prefill`, {}),
    onSuccess: (r) => {
      setError(r.written === 0 ? t('AI proposed nothing new for this row.') : '')
      setLastCost(r.cost ?? null)
      refresh()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Prefill failed')),
  })
  const validateAll = useMutation({
    mutationFn: () => api.post<{ validated: number }>(
      `${API(pid)}/values/validate-all`, {}),
    onSuccess: (r) => {
      setError(r.validated === 0 ? t('No AI cell of yours was awaiting validation.') : '')
      refresh()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Validate all failed')),
  })

  if (isLoading || !data) return <p className="text-muted-foreground">{t('Loading…')}</p>
  if (data.rows.length === 0)
    return <p className="text-sm text-muted-foreground">
      {t('No included study yet — the extraction corpus is the set of full-text included records.')}
    </p>

  const rows = onlyMine ? data.rows.filter((r) => r.assigned_to_me) : data.rows
  const pendingAi = data.rows.reduce((n, r) => n + r.studies.reduce((m, s) =>
    m + Object.values(s.cells).flat()
      .filter((c) => c.user_id === me && c.origin === 'ai' && !c.validated).length, 0), 0)

  return (
    <div>
      <div className="mb-2 flex items-center gap-4">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Checkbox checked={onlyMine}
                    onCheckedChange={(v) => setOnlyMine(!!v)} />
          {t('My assignments only')}
        </label>
        <span className="text-xs text-muted-foreground">
          {t('Cell colours:')} <span className="rounded bg-warning/15 px-1 text-warning">{t('AI, to validate')}</span>{' '}
          <span className="rounded border border-success/30 bg-success/15 px-1 text-success">{t('validated')}</span>
        </span>
        <div className="flex-1" />
        {lastCost && (
          <span className="text-xs text-muted-foreground"
                title={`${lastCost.model} · ${lastCost.tokens_in} in / ${lastCost.tokens_out} out`}>
            {t('last AI call {{cost}}', { cost: lastCost.cost_label })}
          </span>
        )}
        <Button variant="outline" size="sm"
                onClick={() => validateAll.mutate()}
                disabled={validateAll.isPending || pendingAi === 0}
                title={t('Accept every AI-filled cell of yours that is still amber')}
                className="border-success/40 text-success hover:bg-success/10 hover:text-success">
          {validateAll.isPending ? t('Validating…')
            : `${t('✓ Validate all AI cells')}${pendingAi ? ` (${pendingAi})` : ''}`}
        </Button>
        <LiveStatus className="text-xs">{error}</LiveStatus>
      </div>
      {/* bounded height (T23): the horizontal scrollbar stays inside the
          viewport instead of below a page-long table; header sticks on top */}
      <div className="max-h-[calc(100vh-14rem)] overflow-auto rounded-lg border border-border bg-card">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="sticky left-0 top-0 z-20 min-w-56 max-w-72 bg-card px-3 py-2 font-medium">{t('Study')}</th>
              <th className="sticky top-0 z-10 bg-card px-2 py-2 font-medium">{t('Design')}</th>
              <th className="sticky top-0 z-10 bg-card px-2 py-2 font-medium"
                  title={data.instrument.score
                    ? t("Critical-appraisal score — 1 point per 'yes' on the design's checklist (~ = appraisal in progress)")
                    : t('Critical appraisal — criteria answered out of the checklist (this instrument has no score)')}>
                {t('Appraisal')}
              </th>
              <th className="sticky top-0 z-10 bg-card px-2 py-2 font-medium">{t('AI')}</th>
              {data.columns.map((c) => (
                <th key={c.id} className="sticky top-0 z-10 min-w-36 bg-card px-2 py-2 font-medium"
                    title={c.description}>{c.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <GridRow key={row.record_id} pid={pid} me={me} row={row}
                       columns={data.columns} scored={data.instrument.score}
                       onPdf={() => openPdf({ projectId: pid,
                         recordId: row.record_id, title: row.title })}
                       onPrefill={() => prefill.mutate(row.record_id)}
                       prefilling={prefill.isPending}
                       refresh={refresh} setError={setError}
                       setCost={setLastCost} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function GridRow({ pid, me, row, columns, scored, onPdf, onPrefill, prefilling,
                   refresh, setError, setCost }: {
  pid: number
  me: number
  row: Row
  columns: Column[]
  scored: boolean
  onPdf: () => void
  onPrefill: () => void
  prefilling: boolean
  refresh: () => void
  setError: (e: string) => void
  setCost: (c: CostInfo | null) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const setDesign = useMutation({
    mutationFn: ({ studyId, design }: { studyId: number; design: string }) =>
      api.put(`${API(pid)}/studies/${studyId}/design`, { design }),
    onSuccess: refresh,
  })
  const addStudy = useMutation({
    mutationFn: (label: string) =>
      api.post(`${API(pid)}/records/${row.record_id}/studies`, { label }),
    onSuccess: () => { setAdding(false); setNewLabel(''); setError(''); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const suggestDesign = useMutation({
    mutationFn: () => api.post<{ design: string; confidence: number
      rationale: string; cost?: CostInfo }>(
      `${API(pid)}/records/${row.record_id}/design/suggest`, {}),
    onSuccess: (r) => {
      setError(r.design === 'other'
        ? t('AI could not qualify this design: {{rationale}}', { rationale: r.rationale.slice(0, 140) })
        : '')
      setCost(r.cost ?? null)
      refresh()
      queryClient.invalidateQueries({ queryKey: ['extraction-jbi', pid] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Suggest failed')),
  })
  const fillEst = useHoverEstimate(pid, row.record_id, 'prefill')
  const designEst = useHoverEstimate(pid, row.record_id, 'design')
  const n = row.studies.length
  return (
    <>
      {row.studies.map((study, i) => (
        <tr key={study.study_id}
            className={cn('align-top', i === n - 1 ? 'border-b border-border'
                                                   : 'border-b border-dashed border-border/60')}>
          {i === 0 && (
            <td rowSpan={n} className="sticky left-0 min-w-56 max-w-72 bg-card px-3 py-1.5">
              <button onClick={onPdf}
                      className="text-left leading-snug text-foreground hover:text-primary">
                {row.title.slice(0, 90)}{row.title.length > 90 ? '…' : ''}
              </button>
              <p className="text-xs text-muted-foreground">
                {(row.authors[0] ?? '?')}{row.authors.length > 1 ? ' et al.' : ''}
                {row.year ? ` · ${row.year}` : ''}
                {!row.assigned_to_me && row.assigned_to.length > 0 && ` · ${t('not yours')}`}
              </p>
              {adding ? (
                <form className="mt-1 flex items-center gap-1"
                      onSubmit={(e) => { e.preventDefault(); addStudy.mutate(newLabel) }}>
                  <Input autoFocus value={newLabel} maxLength={120}
                         onChange={(e) => setNewLabel(e.target.value)}
                         placeholder={t('Study label (e.g. Study 2)')}
                         aria-label={t('Study label')} className="h-6 text-xs" />
                  <Button type="submit" size="sm" className="h-6 px-2 text-xs"
                          disabled={addStudy.isPending}>{t('Add')}</Button>
                  <Button type="button" size="sm" variant="ghost" className="h-6 px-2 text-xs"
                          onClick={() => setAdding(false)}>{t('Cancel')}</Button>
                </form>
              ) : (
                <Button variant="link" size="sm" onClick={() => setAdding(true)}
                        title={t('This article reports more than one study — add a row per study (its own design, cells and appraisal)')}
                        className="h-auto p-0 text-xs">
                  {t('+ study')}
                </Button>
              )}
            </td>
          )}
          <td className="px-2 py-1.5">
            {n > 1 && (
              <StudyLabel pid={pid} study={study} refresh={refresh} setError={setError} />
            )}
            <Select value={study.study_design ?? NO_VALUE}
                    onValueChange={(v) => setDesign.mutate({
                      studyId: study.study_id, design: v === NO_VALUE ? '' : v })}>
              <SelectTrigger className="h-8 max-w-28 text-xs"
                             aria-label={n > 1 ? t('Design of {{label}}', { label: study.label }) : t('Design')}
                             title={study.design_origin === 'ai'
                               ? t('Qualified by AI — override freely') : undefined}>
                <SelectValue placeholder={t('— design —')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_VALUE}>{t('— design —')}</SelectItem>
                {Object.entries(DESIGN_LABELS).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="mt-0.5 flex items-center gap-1">
              {study.design_origin === 'ai' && (
                <span className="text-xs text-warning">AI</span>
              )}
              {i === 0 && (
                <Button variant="link" size="sm"
                        onClick={() => suggestDesign.mutate()}
                        onMouseEnter={designEst.onMouseEnter}
                        disabled={suggestDesign.isPending}
                        title={designEst.cost
                          ? t('Ask the AI to qualify the study design — est. ≈ {{cost}} ({{model}})', { cost: designEst.cost.cost_label, model: designEst.cost.model })
                          : t('Ask the AI to qualify the study design')}
                        className="h-auto gap-1 p-0 text-xs">
                  {suggestDesign.isPending
                    ? '…'
                    : <><Sparkles className="size-3 text-primary" />{t('suggest')}</>}
                  {designEst.cost && <span className="text-muted-foreground">≈{designEst.cost.cost_label}</span>}
                </Button>
              )}
            </div>
          </td>
          <td className="whitespace-nowrap px-2 py-1.5 text-xs tabular-nums"
              title={!study.jbi.scores.length
                ? t('No appraisal yet — fill it in the Critical appraisal tab')
                : scored
                  ? t('Score per assessor (1 point per yes; ~ = in progress)')
                  : t('Criteria answered per assessor')}>
            {study.jbi.scores.length
              ? <span className="font-medium text-foreground">{jbiScoreLabel(study.jbi.scores, scored)}</span>
              : <span className="text-muted-foreground/50">—</span>}
          </td>
          {i === 0 && (
            <td rowSpan={n} className="px-2 py-1.5">
              <Button variant="outline" size="sm"
                      onClick={onPrefill} disabled={prefilling}
                      onMouseEnter={fillEst.onMouseEnter}
                      title={fillEst.blocked ? fillEst.blocked : fillEst.cost
                        ? t('AI prefill from the stored PDF — est. ≈ {{cost}} ({{model}})', { cost: fillEst.cost.cost_label, model: fillEst.cost.model })
                        : t('AI prefill of this row from the stored PDF (on demand)')}
                      className="h-7 gap-1 px-2 text-xs">
                {prefilling ? '…' : <><Sparkles className="size-3 text-primary" />{t('fill')}</>}
                {fillEst.cost && <span className="text-muted-foreground">≈{fillEst.cost.cost_label}</span>}
              </Button>
            </td>
          )}
          {columns.map((col) => (
            <CellEditor key={col.id} pid={pid} me={me} study={study} col={col}
                        refresh={refresh} setError={setError} />
          ))}
        </tr>
      ))}
    </>
  )
}

/** The label of one study of a multi-study article: click to rename, × to
 * remove (never the first study). */
function StudyLabel({ pid, study, refresh, setError }: {
  pid: number
  study: StudyBlock
  refresh: () => void
  setError: (e: string) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(study.label)
  const rename = useMutation({
    mutationFn: () => api.put(`${API(pid)}/studies/${study.study_id}`, { label: draft }),
    onSuccess: () => { setEditing(false); setError(''); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const remove = useMutation({
    mutationFn: () => api.del(`${API(pid)}/studies/${study.study_id}`),
    onSuccess: () => { setError(''); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Remove failed')),
  })
  const hasContent = Object.values(study.cells).some((c) => c.length > 0)
    || study.jbi.n_appraisals > 0
  if (editing) {
    return (
      <form className="mb-1 flex items-center gap-1"
            onSubmit={(e) => { e.preventDefault(); rename.mutate() }}>
        <Input autoFocus value={draft} maxLength={120}
               onChange={(e) => setDraft(e.target.value)}
               aria-label={t('Study label')} className="h-6 max-w-36 text-xs" />
        <Button type="submit" size="sm" className="h-6 px-2 text-xs">{t('Save')}</Button>
      </form>
    )
  }
  return (
    <p className="mb-1 flex items-center gap-1 text-xs font-medium text-foreground">
      <button type="button" onClick={() => { setDraft(study.label); setEditing(true) }}
              title={t('Rename this study')} className="truncate hover:underline">
        {study.label}
      </button>
      {study.position > 0 && (
        <button type="button"
                onClick={() => {
                  if (!hasContent || window.confirm(
                    t('Remove this study with its values and appraisals?'))) remove.mutate()
                }}
                title={t('Remove this study')}
                aria-label={t('Remove study {{label}}', { label: study.label })}
                className="px-1 text-muted-foreground hover:text-destructive">
          ×
        </button>
      )}
    </p>
  )
}

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.join('; ')
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}

function CellEditor({ pid, me, study, col, refresh, setError }: {
  pid: number
  me: number
  study: StudyBlock
  col: Column
  refresh: () => void
  setError: (e: string) => void
}) {
  const { t } = useTranslation()
  const cells = study.cells[String(col.id)] ?? []
  const mine = cells.find((c) => c.user_id === me)
  const others = cells.filter((c) => c.user_id !== me)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  const save = useMutation({
    mutationFn: (value: unknown) => api.put(`${API(pid)}/values`, {
      study_id: study.study_id, column_id: col.id, value, validated: true }),
    onSuccess: () => { setEditing(false); setError(''); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const validate = useMutation({
    mutationFn: () => api.post(`${API(pid)}/values/validate`, {
      study_id: study.study_id, column_id: col.id }),
    onSuccess: refresh,
  })

  const startEdit = () => {
    setDraft(fmtValue(mine?.value))
    setEditing(true)
  }
  const commitRaw = (raw: string) => {
    let value: unknown = raw
    if (col.col_type === 'multi')
      value = raw.split(';').map((s) => s.trim()).filter(Boolean)
    if (raw === '') value = null
    save.mutate(value)
  }

  const stateClass = !mine ? ''
    : mine.origin === 'ai' && !mine.validated ? 'bg-warning/15'
    : mine.validated ? 'bg-success/10' : ''

  return (
    <td className={cn('min-w-36 px-2 py-1.5', stateClass)}>
      {editing ? (
        col.col_type === 'bool' ? (
          <Select defaultOpen value={draft === '' ? NO_VALUE : draft}
                  onValueChange={(v) => commitRaw(v === NO_VALUE ? '' : v)}
                  onOpenChange={(o) => { if (!o) setEditing(false) }}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_VALUE}>—</SelectItem>
              <SelectItem value="yes">{t('yes')}</SelectItem>
              <SelectItem value="no">{t('no')}</SelectItem>
            </SelectContent>
          </Select>
        ) : col.col_type === 'choice' ? (
          <Select defaultOpen value={draft === '' ? NO_VALUE : draft}
                  onValueChange={(v) => commitRaw(v === NO_VALUE ? '' : v)}
                  onOpenChange={(o) => { if (!o) setEditing(false) }}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_VALUE}>—</SelectItem>
              {col.options.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
            </SelectContent>
          </Select>
        ) : (
          <textarea autoFocus value={draft} rows={col.col_type === 'text' ? 3 : 1}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => commitRaw(draft)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (col.col_type !== 'text' || e.ctrlKey)) {
                        e.preventDefault(); commitRaw(draft)
                      }
                      if (e.key === 'Escape') setEditing(false)
                    }}
                    placeholder={col.col_type === 'multi' ? 'a; b; c' : ''}
                    className="w-full rounded-md border border-input bg-transparent p-1 text-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50" />
        )
      ) : (
        <div className="flex items-start gap-1">
          <button type="button" onClick={startEdit} title={t('Click to edit')}
                  className="min-h-5 flex-1 cursor-text whitespace-pre-wrap rounded-sm text-left leading-snug text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
            {fmtValue(mine?.value) || (
              <>
                <span aria-hidden className="text-muted-foreground/50">—</span>
                <span className="sr-only">{t('empty')}</span>
              </>
            )}
          </button>
          {/* WCAG 1.4.1: the AI / validated state is carried by an icon and
              text as well, not by the amber / green background alone */}
          {mine && mine.origin === 'ai' && !mine.validated && (
            <Button variant="outline" size="sm"
                    onClick={() => validate.mutate()}
                    title={t('AI-filled value, not yet validated — click to accept it')}
                    className="h-5 shrink-0 gap-0.5 border-warning/40 px-1 text-xs text-warning hover:bg-warning/10 hover:text-warning">
              <Sparkles className="size-3" aria-hidden />
              {t('✓ accept')}
            </Button>
          )}
          {mine && mine.origin === 'ai' && mine.validated && (
            <span className="mt-0.5 inline-flex shrink-0 items-center text-success"
                  title={t('AI value, accepted')}>
              <Sparkles className="size-3" aria-hidden />
              <Check className="size-3" aria-hidden />
              <span className="sr-only">{t('AI value, accepted')}</span>
            </span>
          )}
        </div>
      )}
      {others.length > 0 && (
        <p className="mt-0.5 border-t border-dashed border-border pt-0.5 text-xs text-muted-foreground"
           title={t("Other extractor's value (double extraction)")}>
          {others.map((o) => fmtValue(o.value) || '—').join(' / ')}
          {mine && others.some((o) => fmtValue(o.value) !== fmtValue(mine.value)) && (
            <span className="text-destructive"> ≠</span>
          )}
        </p>
      )}
    </td>
  )
}

// ---- JBI tab ---------------------------------------------------------------------

interface Appraisal {
  user_id: number
  user: string
  design: string
  answers: Record<string, { answer: string; comment: string }>
  overall: string
  comment: string
}

function JbiTab({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const { data: table } = useQuery<TableData>({
    queryKey: ['extraction-table', pid],
    queryFn: () => api.get(`${API(pid)}/table`),
  })
  const { data: catalogue } = useQuery<{
    checklists: Checklist[]
    instrument: InstrumentSummary
    overall_options: string[] }>({
    queryKey: ['jbi-checklists', pid],
    queryFn: () => api.get(`${API(pid)}/jbi/checklists`),
  })
  const [studyId, setStudyId] = useState<number | null>(null)
  const rows = table?.rows ?? []
  const entries = rows.flatMap((r) => r.studies.map((s) => ({ row: r, study: s })))
  const selected = entries.find((e) => e.study.study_id === studyId) ?? null

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[20rem_1fr]">
      <Card className="max-h-[75vh] overflow-y-auto p-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">
          {t('Included studies — pick one to appraise')}
        </p>
        <div className="mb-2 flex gap-1.5"
             title={t('Dedicated appraisal table: one line per study × assessor, one column per criterion of the instrument (plus the score when it has one)')}>
          <Button asChild variant="outline" size="sm" className="h-7 px-2 text-xs">
            <a href={`${API(pid)}/export/jbi.csv`}>{t('⤓ Appraisal table (CSV)')}</a>
          </Button>
          <Button asChild variant="outline" size="sm" className="h-7 px-2 text-xs">
            <a href={`${API(pid)}/export/jbi.xlsx`}>{t('⤓ Appraisal table (XLSX)')}</a>
          </Button>
        </div>
        <ul className="space-y-1">
          {entries.map(({ row: r, study: s }) => (
            <li key={s.study_id}>
              <button onClick={() => setStudyId(s.study_id)}
                      className={cn('w-full rounded-md border px-2 py-1.5 text-left text-xs',
                        studyId === s.study_id
                          ? 'border-border bg-accent'
                          : 'border-transparent hover:bg-accent')}>
                <p className="leading-snug text-foreground">
                  {r.title.slice(0, 80)}{r.title.length > 80 ? '…' : ''}
                  {r.studies.length > 1 && <span className="font-medium"> – {s.label}</span>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {s.study_design
                    ? t(DESIGN_LABELS[s.study_design] ?? s.study_design)
                    : t('design not qualified')}
                  {' · '}
                  {s.jbi.n_appraisals > 0
                    ? t('{{count}} appraisal(s)', { count: s.jbi.n_appraisals }) : t('not appraised')}
                  {s.jbi.mine_done ? ` · ${t('mine ✓')}` : ''}
                  {s.jbi.scores.length > 0 && (
                    <span className="ml-1 rounded bg-muted px-1 font-medium tabular-nums text-foreground"
                          title={table?.instrument.score
                            ? t('Score (1 point per yes; ~ = in progress)')
                            : t('Criteria answered')}>
                      {jbiScoreLabel(s.jbi.scores, table?.instrument.score ?? true)}
                    </span>
                  )}
                </p>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {selected && catalogue ? (
        <AppraisalForm key={selected.study.study_id} pid={pid} row={selected.row}
                       study={selected.study} catalogue={catalogue.checklists}
                       instrument={catalogue.instrument} />
      ) : (
        <p className="py-10 text-center text-sm text-muted-foreground">
          {t('Select a study on the left. If its design is not qualified yet, do it from the Table tab (dropdown or ✨ AI suggestion).')}
        </p>
      )}
      {/* The attribution belongs to whichever instrument is actually in use:
          crediting JBI under a checklist the team wrote itself would be a
          false citation, not a courtesy. */}
      <p className="border-t pt-2 text-xs leading-relaxed text-muted-foreground lg:col-span-2">
        {catalogue?.instrument.key === 'jbi' ? (
          <>
            {/* Bibliographic reference, deliberately not run through t(): a
                citation is quoted in its original form. Only the trademark
                notice is localised. */}
            Joanna Briggs Institute. (2017). <i>JBI Critical Appraisal Tools for use in
            JBI Systematic Reviews</i>. JBI.{' '}
            <a href="https://jbi.global" target="_blank" rel="noreferrer"
               className="underline underline-offset-2 hover:text-foreground">jbi.global</a>
            {' — '}
            {t('JBI is a registered trademark of the Joanna Briggs Institute. LitUbik is not affiliated with, nor endorsed by, JBI.')}
          </>
        ) : catalogue?.instrument.key === 'mmat' ? (
          <>
            {/* Same rule: the reference is quoted as published, only the
                usage note is localised. */}
            Hong, Q. N., Pluye, P., Fàbregues, S., Bartlett, G., Boardman, F., Cargo, M.,
            Dagenais, P., Gagnon, M.-P., Griffiths, F., Nicolau, B., O’Cathain, A.,
            Rousseau, M.-C., & Vedel, I. (2018). <i>Mixed Methods Appraisal Tool (MMAT),
            version 2018. User guide.</i> McGill University.{' '}
            <a href="http://mixedmethodsappraisaltoolpublic.pbworks.com" target="_blank"
               rel="noreferrer" className="underline underline-offset-2 hover:text-foreground">
              mixedmethodsappraisaltoolpublic.pbworks.com
            </a>
            {' — '}
            {t('The MMAT is free and its use is open for any education and research activity. It is reproduced here without its explanations of each criterion: read the user guide before appraising. LitUbik is not affiliated with its authors.')}
          </>
        ) : catalogue ? (
          <>
            {t('Instrument declared by this project:')}{' '}
            <span className="text-foreground">{catalogue.instrument.label}</span>
            {catalogue.instrument.citation && ` — ${catalogue.instrument.citation}`}
            {catalogue.instrument.url && (
              <> · <a href={catalogue.instrument.url} target="_blank" rel="noreferrer"
                      className="underline underline-offset-2 hover:text-foreground">
                {catalogue.instrument.url}
              </a></>
            )}
          </>
        ) : null}
      </p>
    </div>
  )
}

const OVERALL_LABELS: Record<string, string> = {
  include: '✓ Include', exclude: '✗ Exclude', seek_info: '? Seek further info',
}

function AppraisalForm({ pid, row, study, catalogue, instrument }: {
  pid: number
  row: Row
  study: StudyBlock
  catalogue: Checklist[]
  instrument: InstrumentSummary
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const jbiUrl = `${API(pid)}/records/${row.record_id}/jbi?study_id=${study.study_id}`
  const { data } = useQuery<{ design: string | null; mine: Appraisal | null
    others: Appraisal[] }>({
    queryKey: ['extraction-jbi', pid, study.study_id],
    queryFn: () => api.get(jbiUrl),
  })
  const design = data?.design ?? study.study_design
  const checklist = catalogue.find((c) => c.key === design)
  const [answers, setAnswers] = useState<Record<string, { answer: string; comment: string }>>({})
  const [overall, setOverall] = useState('')
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  // questions whose current answer came from the AI and awaits review
  const [aiQids, setAiQids] = useState<Set<string>>(new Set())
  const [aiCost, setAiCost] = useState<CostInfo | null>(null)
  const jbiEst = useHoverEstimate(pid, row.record_id, 'jbi')

  const suggest = useMutation({
    mutationFn: () => api.post<{
      answers: Record<string, { answer: string; comment: string }>
      cost?: CostInfo }>(
      `${API(pid)}/records/${row.record_id}/jbi/suggest`),
    onSuccess: (r) => {
      setError('')
      setAiCost(r.cost ?? null)
      const filled = new Set<string>()
      setAnswers((a) => {
        const next = { ...a }
        for (const [qid, s] of Object.entries(r.answers)) {
          if (next[qid]?.answer) continue // never overwrite my answers
          next[qid] = { answer: s.answer, comment: s.comment }
          filled.add(qid)
        }
        return next
      })
      setAiQids(filled)
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('AI suggestion failed')),
  })

  useEffect(() => {
    if (data?.mine) {
      setAnswers(data.mine.answers)
      setOverall(data.mine.overall)
      setComment(data.mine.comment)
    }
  }, [data?.mine])

  const save = useMutation({
    mutationFn: () => api.put(jbiUrl, { answers, overall, comment }),
    onSuccess: () => {
      setError(''); setSaved(true); setAiQids(new Set())
      setTimeout(() => setSaved(false), 2000)
      queryClient.invalidateQueries({ queryKey: ['extraction-jbi', pid, study.study_id] })
      queryClient.invalidateQueries({ queryKey: ['extraction-table', pid] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  if (!checklist)
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        {design === 'other'
          ? t('This study\'s design is "other" — no checklist of this instrument applies.')
          : design
            ? t('{{instrument}} has no checklist for this study design.', { instrument: t(instrument.label) })
            : t("This study's design is not qualified yet — set it from the Table tab.")}
      </p>
    )

  const set = (qid: string, patch: Partial<{ answer: string; comment: string }>) => {
    setAiQids((s) => {
      if (!s.has(qid)) return s
      const next = new Set(s); next.delete(qid); return next
    })
    setAnswers((a) => {
      const prev = a[qid] ?? { answer: '', comment: '' }
      return { ...a, [qid]: { ...prev, ...patch } }
    })
  }

  return (
    <Card className="max-h-[75vh] overflow-y-auto p-4">
      <div className="flex items-center gap-3">
        <h3 className="flex-1 text-sm font-semibold text-foreground">
          {instrument.builtin ? t(checklist.label) : checklist.label}
        </h3>
        <Button variant="outline" size="sm"
                onClick={() => suggest.mutate()}
                onMouseEnter={jbiEst.onMouseEnter}
                disabled={suggest.isPending || !row.has_pdf}
                title={!row.has_pdf ? t('No stored PDF for this record')
                  : jbiEst.blocked ? jbiEst.blocked
                  : jbiEst.cost
                    ? t('AI reads the PDF and proposes an answer + evidence per item — est. ≈ {{cost}} ({{model}}). Nothing is saved until you do.', { cost: jbiEst.cost.cost_label, model: jbiEst.cost.model })
                    : t('AI reads the stored PDF and proposes an answer + evidence per item — nothing is saved until you do')}>
          {suggest.isPending
            ? t('Reading the PDF…')
            : <><Sparkles className="size-3.5 text-primary" />{t('AI suggestions')}</>}
          {jbiEst.cost && row.has_pdf && <span className="text-muted-foreground"> · ≈{jbiEst.cost.cost_label}</span>}
        </Button>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        {row.title}{row.studies.length > 1 && <span className="font-medium"> – {study.label}</span>}
      </p>
      {aiQids.size > 0 && (
        <p className="mb-3 rounded-md border border-border border-l-2 border-l-primary bg-accent px-3 py-2 text-xs text-muted-foreground">
          <Sparkles className="mr-1 inline size-3.5 text-primary" />
          {t('{{count}} answer(s) proposed by the AI (highlighted) — review each against the paper, edit where needed, then save. Nothing is recorded until you save.', { count: aiQids.size })}
          {aiCost && (
            <span title={`${aiCost.model} · ${aiCost.tokens_in} in / ${aiCost.tokens_out} out`}>
              {' '}{t('AI call cost {{cost}}.', { cost: aiCost.cost_label })}
            </span>
          )}
        </p>
      )}
      {data && data.others.length > 0 && (
        <p className="mb-3 rounded-md bg-muted px-3 py-1.5 text-xs text-muted-foreground">
          {t('Also appraised by {{list}} — their answers appear under each question.',
             { list: data.others.map((o) =>
               `${o.user} (${o.overall ? t(OVERALL_LABELS[o.overall] ?? o.overall) : t('in progress')})`).join(', ') })}
        </p>
      )}
      {checklist.domains.map((domain, di) => (
        <div key={di} className="mb-3">
          {domain.label && (
            <p className="mb-1 rounded bg-muted px-2 py-1 text-xs font-semibold text-foreground">
              {instrument.builtin ? t(domain.label) : domain.label}
              {domain.optional && (
                <span className="ml-1 font-normal text-muted-foreground">
                  · {t('optional')}
                </span>
              )}
            </p>
          )}
          {domain.questions.map((q) => {
            const mine = answers[q.id] ?? { answer: '', comment: '' }
            const fromAi = aiQids.has(q.id)
            return (
              <div key={q.id}
                   className={cn('border-b border-border py-2',
                     fromAi && '-mx-2 rounded bg-accent px-2')}>
                <p className="mb-1 text-xs text-foreground">
                  <span className="font-mono text-muted-foreground">{criterionNumber(q.id)}.</span>{' '}
                  {instrument.builtin ? t(q.text) : q.text}
                  {fromAi && (
                    <Badge variant="outline" className="ml-1">
                      <Sparkles className="text-primary" />{t('AI — to review')}
                    </Badge>
                  )}
                </p>
                <div className="flex flex-wrap items-center gap-1.5">
                  {checklist.options.map((option) => (
                    <Button key={option} type="button" size="sm"
                            variant={mine.answer === option
                              ? option === 'yes' ? 'success'
                                : option === 'no' ? 'destructive' : 'secondary'
                              : 'outline'}
                            onClick={() => set(q.id, { answer:
                              mine.answer === option ? '' : option })}
                            className="h-7 rounded-full px-2.5 text-xs">
                      {t(answerLabel(checklist, option))}
                    </Button>
                  ))}
                  <Input value={mine.comment}
                         onChange={(e) => set(q.id, { comment: e.target.value })}
                         placeholder={t('comment / justification…')}
                         className="h-7 min-w-40 flex-1 text-xs" />
                </div>
                {(data?.others ?? []).filter((o) => o.answers[q.id]?.answer).map((o) => (
                  <p key={o.user_id} className="mt-0.5 text-xs text-muted-foreground">
                    {o.user}: {t(answerLabel(checklist, o.answers[q.id].answer))}
                    {o.answers[q.id].comment ? ` — ${o.answers[q.id].comment}` : ''}
                  </p>
                ))}
              </div>
            )
          })}
        </div>
      ))}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {instrument.score ? (
          <Badge variant="outline" className="tabular-nums"
                 title={t("Score — 1 point per 'yes' over the checklist")}>
            {t('Score: {{yes}}/{{total}} yes',
               { yes: Object.values(answers).filter((a) => a.answer === 'yes').length,
                 total: checklist.domains.reduce((s, d) => s + d.questions.length, 0) })}
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground"
                title={t('This instrument discourages any overall score: the appraisal is the rating of each criterion, reported as such.')}>
            {t('No overall score — each criterion is reported on its own.')}
          </span>
        )}
        {instrument.overall && (
          <>
            <span className="text-xs font-medium text-muted-foreground">{t('Overall appraisal:')}</span>
            {Object.entries(OVERALL_LABELS).map(([k, v]) => (
              <Button key={k} size="sm"
                      variant={overall === k ? 'default' : 'outline'}
                      onClick={() => setOverall(overall === k ? '' : k)}
                      className="h-7 rounded-full px-2.5 text-xs">
                {t(v)}
              </Button>
            ))}
          </>
        )}
      </div>
      <Textarea value={comment} onChange={(e) => setComment(e.target.value)}
                placeholder={t('Overall comments…')} rows={2}
                className="mt-2 text-xs" />
      <div className="mt-2 flex items-center gap-3">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {t('Save appraisal')}
        </Button>
        {saved && <span className="text-xs text-success">{t('✓ saved')}</span>}
        <LiveStatus className="text-xs">{error}</LiveStatus>
      </div>
    </Card>
  )
}

// ---- Settings tab -----------------------------------------------------------------

function SettingsTab({ pid, info }: { pid: number; info: ConfigInfo }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [nExtractors, setNExtractors] = useState(info.config?.n_extractors ?? 1)
  const [extractors, setExtractors] = useState<number[]>(
    info.config?.extractor_ids ?? [])
  const [error, setError] = useState('')
  const [suggested, setSuggested] = useState<{ name: string; col_type: string
    description: string; options: string[] }[] | null>(null)
  const [suggestCost, setSuggestCost] = useState<CostInfo | null>(null)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['extraction-config', pid] })
    queryClient.invalidateQueries({ queryKey: ['extraction-table', pid] })
    queryClient.invalidateQueries({ queryKey: ['extraction-columns', pid] })
  }
  const saveConfig = useMutation({
    mutationFn: () => api.put(`${API(pid)}/config`, {
      n_extractors: nExtractors, extractor_ids: extractors }),
    onSuccess: () => { setError(''); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const start = useMutation({
    mutationFn: async () => {
      await api.put(`${API(pid)}/config`, {
        n_extractors: nExtractors, extractor_ids: extractors })
      return api.post<{ assignments_created: number }>(`${API(pid)}/start`, {})
    },
    onSuccess: () => { setError(''); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Start failed')),
  })
  const { data: templates = [] } = useQuery<TemplateInfo[]>({
    queryKey: ['extraction-templates', pid],
    queryFn: () => api.get(`${API(pid)}/columns/templates`),
  })
  const addTemplate = useMutation({
    mutationFn: (template?: string) => api.post<{ created: number }>(
      `${API(pid)}/columns/template`, template ? { template } : {}),
    onSuccess: refresh,
  })
  const suggest = useMutation({
    mutationFn: () => api.post<{ columns: typeof suggested; cost?: CostInfo }>(
      `${API(pid)}/columns/suggest`, {}),
    onSuccess: (r) => { setError(''); setSuggested(r.columns); setSuggestCost(r.cost ?? null) },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Suggest failed')),
  })
  const toggle = (uid: number) =>
    setExtractors((xs) => xs.includes(uid)
      ? xs.filter((x) => x !== uid) : [...xs, uid])

  return (
    <div className="max-w-2xl space-y-4">
      <Card className="p-4">
        <h2 className="mb-2 text-sm font-semibold text-foreground">{t('Extractors')}</h2>
        <p className="mb-2 text-xs text-muted-foreground">
          {t('{{count}} full-text-included record(s) to extract.', { count: info.eligible_records })}
        </p>
        <RadioGroup value={String(nExtractors)}
                    onValueChange={(v) => setNExtractors(Number(v))}
                    className="mb-3 flex gap-4">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <RadioGroupItem value="1" />
            {t('1 extractor per article (split between extractors)')}
          </label>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <RadioGroupItem value="2" />
            {t('2 per article (double extraction, compared)')}
          </label>
        </RadioGroup>
        <div className="mb-3 flex flex-col gap-1.5">
          {info.members.map((m) => (
            <label key={m.user_id}
                   className="flex items-center gap-2 text-sm text-muted-foreground">
              <Checkbox checked={extractors.includes(m.user_id)}
                        onCheckedChange={() => toggle(m.user_id)} />
              {m.display_name}
            </label>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => saveConfig.mutate()}
                  disabled={saveConfig.isPending}>
            {t('Save')}
          </Button>
          <Button onClick={() => start.mutate()}
                  disabled={start.isPending || extractors.length === 0}>
            {info.config?.status === 'active'
              ? t('Re-run allocation (new records only)') : t('Start extraction')}
          </Button>
        </div>
        <LiveStatus className="mt-2 text-xs">{error}</LiveStatus>
      </Card>

      <ColumnManager pid={pid} onError={setError} />

      <Card className="p-4">
        <h2 className="mb-2 text-sm font-semibold text-foreground">{t('Column helpers')}</h2>
        <p className="mb-2 text-xs text-muted-foreground">
          {t('A template only adds the columns whose name is not already used — highlighted is the one this review type suggests, but any of them can be picked and mixed.')}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {templates.map((tpl) => (
            <Button key={tpl.key} variant={tpl.is_default ? 'default' : 'outline'}
                    onClick={() => addTemplate.mutate(tpl.key)}
                    disabled={addTemplate.isPending} title={t(tpl.description)}>
              {t(tpl.label)} ({t('{{count}} columns', { count: tpl.n_columns })})
            </Button>
          ))}
          <Button variant="outline" onClick={() => suggest.mutate()}
                  disabled={suggest.isPending}>
            {suggest.isPending
              ? t('Asking the AI…')
              : <><Sparkles className="size-3.5 text-primary" />{t('Suggest columns from the protocol')}</>}
          </Button>
          {suggestCost && (
            <span className="text-xs text-muted-foreground"
                  title={`${suggestCost.model} · ${suggestCost.tokens_in} in / ${suggestCost.tokens_out} out`}>
              {t('cost {{cost}}', { cost: suggestCost.cost_label })}
            </span>
          )}
        </div>
        {suggested && (
          <SuggestedColumns pid={pid} suggestions={suggested}
                            onDone={() => { setSuggested(null); refresh() }} />
        )}
      </Card>

      <ImportTableCard pid={pid} onDone={refresh} />
    </div>
  )
}

// ---- external extraction-table import ---------------------------------------------

interface ImportHeader {
  index: number
  header: string
  role: string
  column_id: number | null
  column_name: string | null
}

interface ImportPreview {
  headers: ImportHeader[]
  n_rows: number
  matched: number
  matched_not_included: number
  unmatched: number
  unmatched_sample: string[]
}

interface ImportResult {
  n_rows: number
  matched: number
  records_created: number
  records_force_included: number
  columns_created: number
  cells_written: number
  skipped_rows: number
  warnings: string[]
}

const META_ROLE_LABELS: Record<string, string> = {
  title: 'Title', doi: 'DOI', authors: 'Authors', year: 'Year',
  journal: 'Journal', abstract: 'Abstract',
}

function ImportTableCard({ pid, onDone }: { pid: number; onDone: () => void }) {
  const { t } = useTranslation()
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<ImportHeader[]>([])
  const [createMissing, setCreateMissing] = useState(true)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState('')
  const { data: columns = [] } = useQuery<Column[]>({
    queryKey: ['extraction-columns', pid],
    queryFn: () => api.get(`${API(pid)}/columns`),
  })

  const analyse = useMutation({
    mutationFn: (f: File) =>
      api.upload<ImportPreview>(`${API(pid)}/import-table/preview`, f),
    onSuccess: (p) => { setError(''); setResult(null); setPreview(p); setMapping(p.headers) },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Preview failed')),
  })
  const doImport = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('no file')
      const form = new FormData()
      form.append('file', file)
      form.append('mapping', JSON.stringify(mapping.map((m) => ({
        index: m.index, role: m.role, column_id: m.column_id }))))
      form.append('create_missing', String(createMissing))
      const res = await fetch(`${API(pid)}/import-table`, {
        method: 'POST', credentials: 'include', body: form })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new ApiError(res.status, data.detail ?? res.statusText)
      }
      return res.json() as Promise<ImportResult>
    },
    onSuccess: (r) => {
      setError(''); setResult(r); setPreview(null); setFile(null)
      onDone()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Import failed')),
  })

  const pick = (f: File | null) => {
    if (!f) return
    setFile(f)
    analyse.mutate(f)
  }
  const setRole = (index: number, value: string) => {
    setMapping((m) => m.map((h) => {
      if (h.index !== index) return h
      if (value.startsWith('col:')) {
        const id = Number(value.slice(4))
        return { ...h, role: 'column', column_id: id,
                 column_name: columns.find((c) => c.id === id)?.name ?? null }
      }
      return { ...h, role: value === 'new' ? 'column' : value,
               column_id: null, column_name: null }
    }))
  }
  const roleValue = (h: ImportHeader) =>
    h.role === 'column' ? (h.column_id ? `col:${h.column_id}` : 'new') : h.role

  return (
    <Card className="p-4">
      <h2 className="mb-1 text-sm font-semibold text-foreground">
        {t('Import an extraction table (xlsx)')}
      </h2>
      <p className="mb-2 text-xs text-muted-foreground">
        {t('Continue a review started on another platform: upload its extraction table, map the columns, and the articles arrive here already included — with their extracted values ready to complete. Missing articles can be created on the fly.')}
      </p>
      <input ref={fileInput} type="file" accept=".xlsx" className="hidden"
             onChange={(e) => pick(e.target.files?.[0] ?? null)} />
      <Button variant="outline" size="sm"
              onClick={() => fileInput.current?.click()}
              disabled={analyse.isPending}>
        {analyse.isPending ? t('Analysing…') : t('Choose an .xlsx file')}
      </Button>
      {preview && (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-muted-foreground">
            {t('{{rows}} row(s): {{matched}} match an existing article, {{unmatched}} unknown.',
               { rows: preview.n_rows, matched: preview.matched,
                 unmatched: preview.unmatched })}
            {preview.unmatched_sample.length > 0 && (
              <span title={preview.unmatched_sample.join('\n')}>
                {' '}{t('(hover for examples)')}
              </span>
            )}
          </p>
          <div className="max-h-64 space-y-1 overflow-y-auto rounded-md border border-border p-2">
            {mapping.map((h) => (
              <div key={h.index} className="flex items-center gap-2">
                <span className="w-48 truncate text-xs font-medium text-foreground"
                      title={h.header}>{h.header || '—'}</span>
                <span className="text-muted-foreground">→</span>
                <Select value={roleValue(h)}
                        onValueChange={(v) => setRole(h.index, v)}>
                  <SelectTrigger className="h-7 w-56 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ignore">{t('— ignore —')}</SelectItem>
                    {Object.entries(META_ROLE_LABELS).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{t('article {{field}}', { field: t(v) })}</SelectItem>
                    ))}
                    <SelectItem value="new">
                      {t('new column "{{name}}"', { name: h.header })}
                    </SelectItem>
                    {columns.map((c) => (
                      <SelectItem key={c.id} value={`col:${c.id}`}>
                        {t('column: {{name}}', { name: c.name })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox checked={createMissing}
                      onCheckedChange={(v) => setCreateMissing(!!v)} />
            {t('Create the articles not found in this project ({{count}})',
               { count: preview.unmatched })}
          </label>
          <Button size="sm" onClick={() => doImport.mutate()}
                  disabled={doImport.isPending}>
            {doImport.isPending ? t('Importing…') : t('Import the table')}
          </Button>
        </div>
      )}
      {result && (
        <div className="mt-3 rounded-md border border-success/30 bg-success/10 p-3 text-xs text-foreground">
          <p>
            {t('✓ Imported: {{cells}} cell(s) on {{matched}} article(s) — {{created}} article(s) created, {{cols}} column(s) added.',
               { cells: result.cells_written, matched: result.matched,
                 created: result.records_created, cols: result.columns_created })}
            {result.skipped_rows > 0 && (
              <> {t('{{count}} unmatched row(s) skipped.', { count: result.skipped_rows })}</>
            )}
          </p>
          {result.warnings.length > 0 && (
            <ul className="mt-1 list-inside list-disc text-warning">
              {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
        </div>
      )}
      <LiveStatus className="mt-2 text-xs">{error}</LiveStatus>
    </Card>
  )
}

function SuggestedColumns({ pid, suggestions, onDone }: {
  pid: number
  suggestions: { name: string; col_type: string; description: string
    options: string[] }[]
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [picked, setPicked] = useState<Set<number>>(
    new Set(suggestions.map((_, i) => i)))
  const add = useMutation({
    mutationFn: async () => {
      for (const [i, s] of suggestions.entries()) {
        if (picked.has(i)) await api.post(`${API(pid)}/columns`, s)
      }
    },
    onSuccess: onDone,
  })
  return (
    <div className="mt-3 rounded-md border border-border border-l-2 border-l-primary bg-accent p-3">
      <p className="mb-2 text-xs font-medium text-foreground">
        <Sparkles className="mr-1 inline size-3.5 text-primary" />
        {t("AI proposal — untick what you don't want, then add:")}
      </p>
      <ul className="mb-2 space-y-1">
        {suggestions.map((s, i) => (
          <li key={i}>
            <label className="flex items-start gap-2 text-xs text-muted-foreground">
              <Checkbox checked={picked.has(i)} className="mt-0.5"
                        onCheckedChange={() => setPicked((p) => {
                          const n = new Set(p)
                          if (n.has(i)) n.delete(i); else n.add(i)
                          return n
                        })} />
              <span>
                <span className="font-medium text-foreground">{s.name}</span>
                {' '}<span className="text-muted-foreground">({s.col_type}
                {s.options.length ? `: ${s.options.join(', ')}` : ''})</span>
                {s.description && <> — {s.description}</>}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <Button size="sm" onClick={() => add.mutate()} disabled={add.isPending}>
        {t('Add {{count}} column(s)', { count: picked.size })}
      </Button>
    </div>
  )
}

function ColumnManager({ pid, onError }: { pid: number; onError: (e: string) => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: columns = [] } = useQuery<Column[]>({
    queryKey: ['extraction-columns', pid],
    queryFn: () => api.get(`${API(pid)}/columns`),
  })
  const [name, setName] = useState('')
  const [colType, setColType] = useState<Column['col_type']>('text')
  const [options, setOptions] = useState('')
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['extraction-columns', pid] })
    queryClient.invalidateQueries({ queryKey: ['extraction-table', pid] })
  }
  const add = useMutation({
    mutationFn: () => api.post(`${API(pid)}/columns`, {
      name, col_type: colType, description: '',
      options: options.split(',').map((s) => s.trim()).filter(Boolean) }),
    onSuccess: () => { setName(''); setOptions(''); onError(''); refresh() },
    onError: (e) => onError(e instanceof ApiError ? e.message : t('Add failed')),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`${API(pid)}/columns/${id}`),
    onSuccess: refresh,
  })

  // T22: reorder columns — native HTML5 drag & drop plus ↑/↓ fallback
  // buttons (keyboard/accessibility). The new order is persisted through the
  // existing PUT position field, one call per moved column.
  const [dragId, setDragId] = useState<number | null>(null)
  const [overId, setOverId] = useState<number | null>(null)
  const reorder = useMutation({
    mutationFn: async (ordered: Column[]) => {
      for (const [i, c] of ordered.entries()) {
        if (c.position !== i) {
          await api.put(`${API(pid)}/columns/${c.id}`, {
            name: c.name, col_type: c.col_type, description: c.description,
            options: c.options, position: i })
        }
      }
    },
    onSuccess: () => { onError(''); refresh() },
    onError: (e) => onError(e instanceof ApiError ? e.message : t('Reorder failed')),
  })
  const moveTo = (fromId: number, toId: number) => {
    if (fromId === toId) return
    const ordered = [...columns]
    const from = ordered.findIndex((c) => c.id === fromId)
    const to = ordered.findIndex((c) => c.id === toId)
    if (from === -1 || to === -1) return
    const [moved] = ordered.splice(from, 1)
    ordered.splice(to, 0, moved)
    reorder.mutate(ordered)
  }
  const nudge = (id: number, delta: number) => {
    const i = columns.findIndex((c) => c.id === id)
    const j = i + delta
    if (i === -1 || j < 0 || j >= columns.length) return
    moveTo(id, columns[j].id)
  }

  return (
    <Card className="p-4">
      <h2 className="mb-1 text-sm font-semibold text-foreground">
        {t('Columns ({{count}})', { count: columns.length })}
      </h2>
      {columns.length > 1 && (
        <p className="mb-2 text-xs text-muted-foreground">
          {t('Drag a column (or use ↑/↓) to change its order in the extraction grid.')}
        </p>
      )}
      <ul className="mb-3 space-y-1">
        {columns.map((c) => (
          <li key={c.id}
              draggable
              onDragStart={() => setDragId(c.id)}
              onDragEnd={() => { setDragId(null); setOverId(null) }}
              onDragOver={(e) => { e.preventDefault(); setOverId(c.id) }}
              onDrop={(e) => {
                e.preventDefault()
                if (dragId !== null) moveTo(dragId, c.id)
                setDragId(null)
                setOverId(null)
              }}
              className={cn(
                'flex cursor-grab items-center gap-2 rounded px-1 text-xs text-muted-foreground',
                dragId === c.id && 'opacity-40',
                overId === c.id && dragId !== null && dragId !== c.id
                  && 'border-t-2 border-primary',
              )}>
            <span className="select-none text-muted-foreground/60" title={t('Drag to reorder')}>⋮⋮</span>
            <span className="font-medium text-foreground">{c.name}</span>
            <span className="text-muted-foreground">{c.col_type}
              {c.options.length ? `: ${c.options.join(', ')}` : ''}</span>
            <span className="flex-1" />
            <Button variant="ghost" size="icon" title={t('Move up')}
                    onClick={() => nudge(c.id, -1)}
                    disabled={reorder.isPending || columns[0]?.id === c.id}
                    className="size-6 text-muted-foreground hover:text-foreground">↑</Button>
            <Button variant="ghost" size="icon" title={t('Move down')}
                    onClick={() => nudge(c.id, 1)}
                    disabled={reorder.isPending
                      || columns[columns.length - 1]?.id === c.id}
                    className="size-6 text-muted-foreground hover:text-foreground">↓</Button>
            <Button variant="ghost" size="icon"
                    onClick={() => remove.mutate(c.id)}
                    title={t('Delete column (removes its values)')}
                    className="size-6 text-muted-foreground hover:text-destructive">✕</Button>
          </li>
        ))}
        {columns.length === 0 && (
          <li className="text-xs text-muted-foreground">
            {t('No column yet — use the template, the AI suggestion, or add below.')}
          </li>
        )}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <Input value={name} onChange={(e) => setName(e.target.value)}
               placeholder={t('Column name')} className="h-8 w-40 text-xs" />
        <Select value={colType}
                onValueChange={(v) => setColType(v as Column['col_type'])}>
          <SelectTrigger className="h-8 w-28 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(['text', 'number', 'bool', 'choice', 'multi'] as const).map((t) => (
              <SelectItem key={t} value={t}>{t}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {(colType === 'choice' || colType === 'multi') && (
          <Input value={options} onChange={(e) => setOptions(e.target.value)}
                 placeholder={t('options, comma-separated')} className="h-8 w-56 text-xs" />
        )}
        <Button variant="secondary" size="sm"
                onClick={() => add.mutate()} disabled={!name || add.isPending}>
          {t('+ Add')}
        </Button>
      </div>
    </Card>
  )
}
