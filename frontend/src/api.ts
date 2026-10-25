// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
// Minimal typed fetch wrapper. Cookies carry the session; same-origin via Vite proxy.

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

async function upload<T>(path: string, file: File,
                         fields?: Record<string, string>): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  for (const [key, value] of Object.entries(fields ?? {}))
    form.append(key, value)
  const res = await fetch(path, { method: 'POST', credentials: 'include', body: form })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
  upload,
}

// ---- API types ----

export interface User {
  id: number
  email: string
  display_name: string
  is_admin: boolean
  // false only for sandbox accounts of a demo instance (M6)
  is_trusted: boolean
  // standalone "Download papers" module, granted by the superadmin (who
  // always has it)
  can_download_papers: boolean
  // demo instance: a one-click guest session (no e-mail, no password)
  is_guest: boolean
}

// public instance profile (M6 demo) + the AGPLv3 §13 source offer
export interface InstanceInfo {
  demo: boolean
  reset_hour: number
  // this host name opens the one-click guest session (demo instances)
  guest_entry: boolean
  // legal pages the instance publishes ("notice", "terms", "privacy")
  legal: string[]
  version: string
  license: string
  source_url: string
}

// demo instance: what the visitors' AI budget has left (/api/demo/ai-budget)
export interface DemoAiBudget {
  applies: boolean
  enabled: boolean
  user_cap_usd?: number
  daily_cap_usd?: number
  monthly_cap_usd?: number
  user_spent_usd?: number
  day_spent_usd?: number
  month_spent_usd?: number
  month_calls?: number
  user_left_usd?: number
  day_left_usd?: number
  month_left_usd?: number
  left_usd?: number
  period?: string
  live_visitors?: number
}

export interface Project {
  id: number
  name: string
  description: string
  research_question: string
  // how the review frames itself — drives vocabulary, not the pipeline
  review_type: string
  question_framework: string
  // PRISMA 2020 item 24a/24b. '' = never answered, 'none' = answered "not
  // registered" — the manuscript owes that statement, so the two differ.
  registry: string
  registration_id: string
  registration_url: string
  registered_at: string | null
  protocol_url: string
  // AI keys: open only the best-ranked key, never fall back to another provider
  llm_no_fallback: boolean
  // AI routing: reviewers may change the provider/model/effort per task too
  llm_reviewers_can_route: boolean
  // the databases this review searches (registry ids); null = every database
  databases: string[] | null
  created_at: string
  archived_at: string | null
  my_role: 'admin' | 'reviewer'
  sync_role: 'coordinator' | 'satellite'
}

// GET /api/registries — where a review can be registered. Served rather than
// hardcoded here, for the same reason as the framings catalogue.
export interface RegistryInfo {
  key: string
  label: string
  id_hint: string
  has_url_template: boolean
}

// GET /api/framings — the catalogue behind the two settings above. Labels are
// English source strings, run through t() like the AI prompt labels are.
export interface FrameworkSlot {
  key: string
  letter: string
  label: string
  hint: string
}

export interface FrameworkInfo {
  key: string
  short: string
  label: string
  citation: string
  slots: FrameworkSlot[]
}

export interface ReviewTypeInfo {
  key: string
  label: string
  citation: string
  default_framework: string
  default_template: string
  // what the software does NOT do for this review type ("" when nothing)
  tooling_note: string
}

export interface Framings {
  review_types: ReviewTypeInfo[]
  frameworks: FrameworkInfo[]
  default_review_type: string
  default_framework: string
}

export interface Member {
  user_id: number | null  // null only for legacy e-mail invitations
  email: string
  display_name: string
  role: 'admin' | 'reviewer'
  // awaiting = account created by the admin, claimed at registration
  status: 'member' | 'awaiting' | 'invited'
}

export interface Credential {
  id: number
  provider: string
  default_model: string
  project_id: number | null
  key_hint: string
  is_default: boolean
  // endpoint of a self-hosted server ('local' provider); '' otherwise
  base_url: string
}

export interface ProviderMeta {
  label: string
  needs_key: boolean   // false for a self-hosted server
  needs_url: boolean   // true when the endpoint is the user's to give
}

export interface ProvidersInfo {
  providers: string[]
  meta: Record<string, ProviderMeta>
  default_models: Record<string, string>
  suggested_models: Record<string, string[]>
  default_local_url: string
  // per-task routing: two tiers of work, each provider's model for each
  tiers: string[]
  tier_models: Record<string, Record<string, string>>
  efforts: string[]
  default_effort: string
}

/** One AI task's routing in a scope: the row stored for that scope (null =
 * inherited) and what a call would actually run on right now. */
export interface TaskRoute {
  task: string
  label: string
  description: string
  tier: string
  features: string[]
  route: { provider: string; model: string; effort: string } | null
  effective: {
    source: 'project' | 'global' | 'default'
    provider: string | null
    model: string | null
    effort: string
    provider_missing: boolean
  }
}

export interface TaskRoutes {
  routes: TaskRoute[]
  available_providers: string[]
}

export interface DatabaseKey {
  provider: string
  label: string
  configured: boolean
  key_hint: string
  project_id: number | null
  global_configured: boolean
  help_url: string
}

// AI prompt transparency (M2): editable instruction block per AI feature
export interface PromptInfo {
  key: string
  label: string
  description: string
  default_text: string
  override_text: string | null
  effective_text: string
}

export interface Criterion {
  code: string
  type: 'include' | 'exclude'
  label: string
  description: string
}

export interface ProtocolSummary {
  id: number
  version: number
  source_filename: string
  generated_with: string
  validated_at: string | null
  created_at: string
  has_content: boolean
}

export interface ProtocolDetail extends ProtocolSummary {
  protocol_md: string
  criteria: Criterion[]
  source_text_chars: number
}

export interface OsfCandidate {
  kind: 'file' | 'form'
  name: string
  download_url?: string
  guid?: string
  size?: number | null
}

export interface OsfImportResult {
  protocol?: ProtocolDetail
  candidates?: OsfCandidate[]
}

export interface Concept {
  id: number
  name: string
  description: string
  keywords: string[]
  position: number
}

export interface DatabaseInfo {
  id: string
  label: string
  count: 'api' | 'manual'
  instructions: string
  // keyed provider (Scopus, IEEE, CORE, Lens, Springer, WoS Starter): automatic
  // once a key is stored, assisted-manual otherwise
  key_required?: boolean
  // set on the databases a project declared itself (assisted-manual only)
  custom?: boolean
  custom_id?: number
  syntax?: string
  url?: string
}

// every database of a project, keyed or not (project settings / setup wizard)
export interface ProjectDatabase {
  id: string
  label: string
  mode: 'api_key' | 'api' | 'manual'
  custom: boolean
  custom_id: number | null
  syntax: string
  url: string
  // whether the review searches it (all are selected until the project chooses)
  selected: boolean
}

// a database the project added by hand
export interface CustomDatabase {
  id: number
  db_id: string
  label: string
  syntax: string
  instructions: string
  url: string
  n_imports: number
}

export interface IdLabel {
  id: string
  label: string
}

export interface DatabasesInfo {
  databases: DatabaseInfo[]
  doc_types: IdLabel[]
  disciplines: IdLabel[]
}

export interface EquationCountRow {
  database_name: string
  count: number
  method: 'api' | 'manual'
  noted_at: string
}

export interface GoldenResults {
  checked_at: string
  database: string
  total: number
  found: number
  missing: string[]
  // which papers were retrieved, as "Smith et al. (2021)" — absent on checks
  // run before this was recorded
  found_refs?: { doi: string; citation: string }[]
}

export interface TranslationDraft {
  from_db: string
  provider: string
  model: string
  at: string
  notes: string[]
  validated: boolean
  validated_by: number | null
  validated_at: string | null
}

// one golden-set check of one variant on one database: `api` = the database
// was asked, `import` = looked up among the records imported from it
export interface RecallRow {
  database_name: string
  method: 'api' | 'import'
  total: number
  found: number
  missing: { doi: string | null; pmid: string | null; citation: string }[]
  checked_at: string
}

export interface Equation {
  id: number
  label: string
  // concepts = built from the concept blocks; raw = typed per database (the
  // queries live in translations.overrides, structure is empty)
  mode: 'concepts' | 'raw'
  // one entry per block of the equation (blocks are AND-ed); `members` lists
  // the concepts OR-ed inside the block — absent on pre-blocks snapshots
  structure: {
    concepts: {
      id?: number
      name: string
      keywords: string[]
      members?: { id: number; name: string }[]
    }[]
  }
  translations: {
    auto: Record<string, string>
    overrides: Record<string, string>
    // queries the AI drafted from another database's text (raw variants):
    // usable at once, flagged until a human validates or edits them
    drafts?: Record<string, TranslationDraft>
  }
  params: {
    year_from?: number | null
    year_to?: number | null
    languages?: string[]
    fields?: string[]
    doc_types?: string[]
    disciplines?: string[]
  }
  status: 'draft' | 'frozen'
  frozen_at: string | null
  golden_results: GoldenResults | null
  created_at: string
  counts: EquationCountRow[]
  // latest check per (database, method)
  recall: RecallRow[]
}

export interface GoldenRef {
  id: number
  doi: string | null
  pmid: string | null
  title: string
  year: number | null
  apa: string
}

/** Cost of an AI call (actual after a call, or estimated before one). */
export interface CostInfo {
  cost_label: string
  cost_usd: number
  model: string
  provider: string
  tokens_in: number
  tokens_out: number
  estimated: boolean
}

export interface ProposeResult {
  research_question: string
  created: Concept[]
  enriched: Concept[]
  cost?: CostInfo | null
}

export interface ImportRow {
  id: number
  source_type: 'database' | 'manual' | 'snowballing'
  source_name: string
  round: number
  equation_id: number | null
  equation_label: string | null
  filename: string
  n_records: number
  imported_by: string | null
  imported_at: string
  // PRISMA-S: declared by the uploader (an API fetch sets searched_at itself)
  searched_at: string | null
  declared_hits: number | null
  // PRISMA-S limits applied to the run (null = not declared)
  date_restricted: boolean | null
  discipline_restricted: boolean | null
  disciplines: string[] | null
  doc_type_restricted: boolean | null
  doc_types: string[] | null
  // the fields the query ran on (title/abstract/keywords/fulltext/all)
  search_fields: string[] | null
}

export interface RecordRow {
  id: number
  doi: string | null
  title: string
  authors: string[]
  year: number | null
  journal: string
  abstract: string
  source_name: string
  dedup_status: string
}

export interface RecordsPage {
  total: number
  items: RecordRow[]
}

export interface AnnotationRect {
  x: number
  y: number
  w: number
  h: number
}

export interface Annotation {
  id: number
  record_id: number
  page: number
  rects: AnnotationRect[]
  quote: string
  note: string
  color: string
  author: string
  author_id: number | null
  created_at: string
  mine: boolean
}

export interface ExclusionReason {
  code: string
  label: string
  description: string
  kind: 'criterion' | 'builtin'
}

// ---- tags on papers (#16/#T13) ----

export interface TagInfo {
  id: number
  name: string
  n_records: number
}

export interface RecordTagInfo {
  id: number
  name: string
}

export interface TaggedRecord {
  record_id: number
  title: string
  authors: string[]
  year: number | null
  journal: string
  doi: string | null
  tags: string[]
  status: string
}

// ---- results / synthesis (M10) ----

export interface CountItem {
  value: string
  n: number
}

export interface YearCount {
  year: number
  n: number
}

export interface CountryCount {
  iso3: string
  name: string
  n: number
}

export interface NumericStats {
  n: number
  min: number
  max: number
  mean: number
  median: number
  q1: number
  q3: number
}

export interface ColumnAggregate {
  id: number
  name: string
  col_type: 'number' | 'bool' | 'choice' | 'multi'
  options: string[]
  n_missing: number
  n_conflicts: number
  distribution?: CountItem[]
  stats?: NumericStats | null
  values?: number[]
}

export type AnswerCounts = { yes: number; no: number; unclear: number; na: number }

/** One row of the per-domain appraisal view: a bias domain (or, for a
 * flat checklist, a single question) with the answers pooled over it. */
export interface AppraisalRow {
  label: string
  counts: AnswerCounts
  answered: boolean
  n_questions: number
}

export interface AppraisalStudyDomains {
  design: string
  granularity: 'domain' | 'question'
  rows: AppraisalRow[]
}

/** A folded block: one study design, its rows pooled across studies. */
export interface AppraisalDomainBlock {
  design: string
  design_label: string
  granularity: 'domain' | 'question'
  n_studies: number
  rows: { label: string; counts: AnswerCounts; n_questions: number; n_studies: number }[]
}

export interface JbiStudySummary {
  record_id: number
  study_id: number
  label: string
  design: string | null
  n_assessors: number
  // which appraisal counted: the one two assessors settled on, or the
  // individual ones pooled
  source: 'consensus' | 'individual'
  overall: string
  answers: AnswerCounts
  n_questions: number
  pct_yes: number
  domains: AppraisalStudyDomains | null
}

export interface StudyRow {
  record_id: number
  study_id: number   // one row per study (chantier 9): an article may yield several
  label: string
  year: number | null
  design: string | null
  countries: string[]           // normalized ISO-3166 alpha-3
  countries_unmatched: string[] // raw values the normalizer did not recognize
  // one consensus cell per chartable column, keyed by column id
  values: Record<string, { v: unknown; s: 'ok' | 'conflict' | 'empty' }>
}

export interface ResultsAggregates {
  n_included: number   // articles (reports)
  n_studies: number    // studies those articles report (chantier 9)
  n_with_any_value: number
  n_fully_validated: number
  extraction_started: boolean
  years: { counts: YearCount[]; unknown: number; min: number | null; max: number | null }
  designs: { design: string | null; n: number }[]
  countries: {
    column_id: number | null
    column_name: string | null
    counts: CountryCount[]
    n_studies_with_country: number
    n_multi_country: number
    unmatched: CountItem[]
    missing: number
  }
  columns: ColumnAggregate[]
  jbi: {
    instrument: { key: string; label: string; citation: string; url: string; builtin: boolean
                  overall: boolean; score: boolean }
    dual: boolean
    by_domain: AppraisalDomainBlock[]
    per_study: JbiStudySummary[]
    n_from_consensus: number
    avg_pct_yes: number | null
    by_design: { design: string | null; n_studies: number; avg_pct_yes: number }[]
    n_appraised: number
  }
  studies: StudyRow[]
}

// ---- synthesis declaration (SWiM) and certainty of the evidence (GRADE) ----

/** A synthesis method and the question it can actually answer (SWiM table 2).
 * The two travel together on purpose: declaring vote counting and then
 * reporting an average effect is the failure SWiM item 9 asks reviews to
 * report as a limitation. */
export interface SynthesisMethodInfo {
  key: string
  label: string
  question: string
  minimum_data: string
  without_meta_analysis: boolean
}

export interface GradeCatalogue {
  frameworks: { key: string; label: string; description: string }[]
  intents: { key: string; label: string }[]
  targets: { key: string; label: string }[]
  starting_points: { key: string; label: string }[]
  downgrade_domains: { key: string; label: string; help: string }[]
  upgrade_domains: { key: string; label: string; help: string }[]
  judgements: { key: string; label: string }[]
  levels: { key: string; label: string }[]
}

export interface SynthesisCatalogue {
  methods: SynthesisMethodInfo[]
  directions: { key: string; label: string }[]
  grade: GradeCatalogue
  /** what this project's question framework calls an outcome (SPIDER: Evaluation) */
  outcome_slot: string
  /** '' when the framework defines no comparator (SPIDER, PEO) */
  comparison_slot: string
}

export interface SynthesisPlanInfo {
  enabled: boolean
  certainty_framework: string
  /** non-empty when GRADE looks like the wrong instrument for this framing */
  certainty_warning: string
  grouping_md: string
  grouping_changes_md: string
  prioritisation_md: string
  heterogeneity_md: string
  presentation_md: string
  limitations_md: string
}

export interface SynthesisOutcomeInfo {
  id: number
  uuid: string
  label: string
  comparison: string
  position: number
  intent: string
  target: string
  thresholds_md: string
  direction: string
  metric: string
  metric_rationale: string
  synthesis_method: string
  synthesis_method_label: string
  synthesis_method_question: string
  method_rationale: string
  study_ids: number[]     // contributing studies (chantier 9)
  record_ids: number[]    // the articles behind them (derived, read-only)
  n_studies: number
  // meta-analysis bridge (chantier 10): measure + role → column mapping
  effect_spec: { measure?: string; mapping?: Record<string, number> }
  finding_md: string
  certainty: { final: string; label: string; statement_md: string
               is_consensus: boolean } | null
}

export interface CertaintyAssessmentInfo {
  id: number
  user_id: number | null
  user: string
  is_consensus: boolean
  starting_point: string
  starting_rationale: string
  domains: Record<string, { judgement: string; note: string }>
  upgrades: Record<string, { applied: boolean; note: string }>
  final: string
  final_label: string
  /** what the arithmetic would give — shown beside the decision, never
   * substituted for it */
  suggested_final: string
  suggested_label: string
  diverges: boolean
  statement_md: string
  updated_at: string
}

export interface CertaintyView {
  outcome: SynthesisOutcomeInfo
  framework: string
  certainty_warning: string
  assessments: CertaintyAssessmentInfo[]
  mine: CertaintyAssessmentInfo | null
  consensus: CertaintyAssessmentInfo | null
  suggestions: {
    starting_point: {
      starting_point: string
      rationale: string
      design_counts: { design: string; label: string; n: number }[]
    }
    risk_of_bias: {
      instrument: string
      dual_assessment: boolean
      n_studies: number
      n_appraised: number
      studies: { record_id: number; study_id: number; study_label: string
                 title: string; design: string | null
                 appraised: boolean; overall: string; source: string
                 n_yes: number | null; n_questions: number | null }[]
      note: string
    }
    publication_bias: {
      databases: string[]
      n_databases: number
      frozen_equation: string | null
      n_imports: number
      grey_literature: boolean
      note: string
    }
  }
  can_write_consensus: boolean
}

export interface SofRow {
  outcome_id: number
  outcome: string
  comparison: string
  n_studies: number
  n_participants: number | null
  metric: string
  synthesis_method: string
  question_answered: string
  finding_md: string
  certainty: string
  certainty_label: string
  statement_md: string
  rated: boolean
}

export interface SofTable {
  framework: string
  framework_label: string
  participants_column: string | null
  rows: SofRow[]
  n_rated: number
}

export interface NarrativeInfo {
  content_md: string
  provider: string
  model: string
  cost: CostInfo
  generated_by_name: string
  created_at: string
}

// ---- reporting: methods paragraph + AI disclosure ----

export type ReportKind = 'methods' | 'ai_disclosure'

/** One activity line of the DAISY-style disclosure form. `level` is
 * pre-answered from the AI-use journal; `note` is the author's own words. */
export interface DisclosureActivity {
  key: string
  label: string
  control: string
  level: 'none' | 'low' | 'medium' | 'high'
  n_calls: number
  features: string[]
  note: string
}

export interface DisclosureForm {
  activities: DisclosureActivity[]
  tools: string[]
  inputs_shared: string[]
  safeguards: string
  human_validation_note: string
  authorship: string
  scope_note: string
}

export interface ReportSectionInfo {
  kind: ReportKind
  lang: 'en' | 'fr'
  content_md: string
  edited_md: string
  form: DisclosureForm | Record<string, never>
  cost: CostInfo
  generated_by_name: string
  created_at: string
  updated_at: string
}

export interface AiUsageEntry {
  feature: string
  label: string
  activity: string | null
  stage: string | null
  inputs: string
  n_calls: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
  cost_label: string
  models: { model: string; n_calls: number }[]
  users: string[]
  first_at: string | null
  last_at: string | null
}

export interface AiDossier {
  usage: AiUsageEntry[]
  evidence: {
    screening: Record<string, {
      n_ai_suggestions: number
      n_decided: number
      n_compared: number
      n_agreed: number
      n_overruled: number
      n_ai_maybe: number
      // after_vote rounds: votes cast after the reviewer chose to look first
      n_revealed_before_vote?: number
      reveal_modes?: string[]
    }>
    triage: { n_validated_exclusions: number }
    extraction: {
      n_cells: number
      n_ai_cells: number
      n_ai_cells_validated: number
      n_designs_classified_by_ai: number
    }
    protocol: { ai_extracted: boolean; validated_by_human: boolean }
  }
  totals: {
    n_calls: number
    cost_usd: number
    cost_label: string
    models: string[]
    first_at: string | null
    last_at: string | null
  }
  form: DisclosureForm
  any_ai_used: boolean
  journal: {
    incomplete: boolean
    first_journal_entry: string | null
    earliest_ai_trace: string | null
  }
}

// ---- sync (inter-instance collaboration, phase 1) ----

export interface SyncInfo {
  project_id: number
  uuid: string
  sync_role: 'coordinator' | 'satellite'
  snapshot_version: number
  coordinator_email: string
  has_passphrase: boolean
  n_shared_keys: number
}

export interface FolderState {
  configured: boolean
  path?: string
  ok?: boolean
  error?: string
  auto_publish?: boolean
  latest_snapshot_version?: number
  update_available?: boolean
  snapshot_behind?: boolean
  pending_contributions?: { author: string; n_new: number }[]
}

export interface FolderScanSummary {
  imported: { author: string; seq: number; conflicts_created: number }[]
  pushed: { author: string; seq: number }[]
  published: number | null
  update_available: boolean
  warnings: string[]
}

export interface SharedKey {
  kind: 'llm' | 'database'
  id: number
  provider: string
  default_model: string
  owner_email: string | null
  shared: boolean
  is_mine: boolean
}

export interface SyncImportReport {
  mode: 'create' | 'update'
  project_id: number
  project_uuid: string
  project_name: string
  snapshot_version: number
  counts: Record<string, number>
  n_votes: number
  kept_local: Record<string, number>
  quarantined_count: number
  quarantined_sample: { type: string; record: string; email?: string }[]
  shadow_users: string[]
  pdfs_missing: number
  credentials?: { applied: number; removed: number; skipped: number }
  folder_linked?: string
  warnings: string[]
}

export interface ContribCounts {
  new: number
  updated: number
  unchanged: number
}

export interface ContribImportReport {
  project_id: number
  project_name: string
  author: string
  seq: number
  based_on_snapshot_version: number
  votes: ContribCounts
  ai_votes: { added: number; skipped: number }
  jbi: ContribCounts
  values: ContribCounts
  annotations: number
  skips: number
  conflicts_created: number
  tickets?: ContribCounts
  ticket_comments?: number
  tags?: { attached: number; removed: number; unchanged: number }
  credentials?: { applied: number; removed: number; skipped: number }
  quarantined_count: number
  quarantined_sample: { type: string; record: string; email?: string }[]
  warnings: string[]
}

export interface SyncEventInfo {
  id: number
  direction: 'export' | 'import'
  kind: 'snapshot' | 'contributions'
  author_email: string
  seq: number
  based_on_version: number
  filename: string
  counts: Record<string, unknown>
  warnings: string[]
  created_at: string
}

export interface JobInfo {
  id: number
  type: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  progress: number
  total: number
  message: string
  params?: Record<string, unknown>
  result: Record<string, unknown>
  error: string
  project_id?: number | null
}

// ---- living review (chantier 5) ----
export interface UpdatePlan {
  project_id: number
  enabled: boolean
  interval_days: number
  databases: string[]
  equation_id: number | null
  last_run_at: string | null
  next_run_at: string | null
  intervals?: number[]
}

export interface UpdateRun {
  id: number
  round: number
  label: string
  n: number | null
  databases: string[]
  since_at: string | null
  n_fetched: number
  n_new_unique: number
  triggered_by: 'schedule' | 'manual' | 'fetch'
  errors: Record<string, string>
  started_at: string | null
  finished_at: string | null
  deletable: boolean
}

export interface NotificationItem {
  id: number
  project_id: number | null
  kind: string
  payload: Record<string, unknown>
  created_at: string
  read_at: string | null
}

// ---- personal integrations (chantier 4: Zotero) ----
export interface ZoteroStatus {
  configured: boolean
  library_type: 'user' | 'group' | null
  library_id: number | null
  library_name: string | null
  username: string | null
  write: boolean
  updated_at: string | null
  key_url: string
}

export interface ZoteroLibrary {
  type: 'user' | 'group'
  id: number
  name: string
  write: boolean
}

export interface ZoteroProbe {
  user_id: number
  username: string
  libraries: ZoteroLibrary[]
}

export interface ZoteroCollection {
  key: string
  name: string
  depth: number
  n_items: number
}

// ---- thematic map (chantier 11) ----
export interface TopicPoint {
  record_id: number
  x: number
  y: number
  cluster: number
  status: 'include' | 'exclude' | 'undecided'
  title: string
  year: number | null
  author: string
}

export interface TopicCluster {
  id: number
  size: number
  terms: string[]
  label: string
  label_is_ai: boolean
}

export interface TopicRunSummary {
  id: number
  scope: 'unique' | 'ta_included' | 'ft_included'
  k: number
  k_requested: number | null
  n_docs: number
  silhouette: number | null
  projection: 'tsne' | 'svd'
  created_at: string
  label_provider: string
  label_model: string
}

export interface TopicRun extends TopicRunSummary {
  points: TopicPoint[]
  clusters: TopicCluster[]
  created_by_name: string
}

export interface TopicsState {
  run: TopicRun | null
  history: TopicRunSummary[]
  sizes: Record<'unique' | 'ta_included' | 'ft_included', number>
  min_docs: number
}

// ---- meta-analysis bridge (chantier 10) ----
export interface EffectMeasure {
  key: string
  label: string
  kind: 'continuous' | 'dichotomous' | 'correlation'
  roles: string[]
  log_scale: boolean
}

export interface EffectMeasures {
  measures: EffectMeasure[]
  role_labels: Record<string, string>
  columns: { id: number; name: string }[]
}

export interface EffectStudy {
  study_id: number
  record_id: number
  label: string
  doi: string | null
  year: number | null
  design: string | null
  raw: Record<string, number | null>
  problems: string[]
  yi?: number
  vi?: number
  se?: number
  ci_low?: number
  ci_high?: number
  estimate?: number
  estimate_low?: number
  estimate_high?: number
}

export interface EffectTable {
  outcome_id: number
  label: string
  comparison: string
  measure: string | null
  measure_label: string
  kind: string
  log_scale: boolean
  mapping: Record<string, { column_id: number; column_name: string }>
  roles: string[]
  role_labels: Record<string, string>
  missing_roles: string[]
  studies: EffectStudy[]
  n_studies: number
  n_computed: number
}
