// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import {
  api, type ColumnAggregate, type Project, type ResultsAggregates,
  type SynthesisCatalogue, type SynthesisPlanInfo,
} from '../api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'
import { Stat } from '@/components/ui/stat'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  NO_FILTERS, filteredAggregates, isFiltering, type ResultsFilters,
} from '@/components/results/filtering'
import ChartCard from '@/components/results/ChartCard'
import BarChart, { type BarItem } from '@/components/results/BarChart'
import { NumericHistogram, YearHistogram } from '@/components/results/Histogram'
import StackedBar from '@/components/results/StackedBar'
import WorldMap from '@/components/results/WorldMap'
import NarrativePanel from '@/components/results/NarrativePanel'
import ThemesTab from '@/components/results/ThemesTab'
import SynthesisPlanPanel from '@/components/synthesis/SynthesisPlanPanel'
import OutcomesPanel from '@/components/synthesis/OutcomesPanel'
import SofTable from '@/components/synthesis/SofTable'
import { useVizPalette } from '@/components/results/palette'
import { svgToPng } from '@/components/results/exportPng'
import { DESIGN_LABELS } from './Extraction'

const API = (pid: number) => `/api/projects/${pid}/results`

const designLabel = (d: string | null) =>
  d ? i18n.t(DESIGN_LABELS[d] ?? d) : i18n.t('Not qualified')

const toggleIn = <T,>(list: T[], v: T) =>
  list.includes(v) ? list.filter((x) => x !== v) : [...list, v]

export default function ResultsPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  type Tab = 'overview' | 'variables' | 'quality' | 'synthesis' | 'narrative' | 'themes'
  const [tab, setTab] = useState<Tab>('overview')
  const palette = useVizPalette()

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data, isLoading } = useQuery<ResultsAggregates>({
    queryKey: ['results', pid],
    queryFn: () => api.get(API(pid)),
  })

  // cross-filters (year range / designs / countries) applied to all charts,
  // recomputed client-side from the per-study consensus rows
  const [filters, setFilters] = useState<ResultsFilters>(NO_FILTERS)
  useEffect(() => setFilters(NO_FILTERS), [pid])
  const view = useMemo(
    () => (data ? filteredAggregates(data, filters) : undefined),
    [data, filters])

  const exportAllCharts = () => {
    document.querySelectorAll<HTMLElement>('[data-export-filename]')
      .forEach((el) => {
        const svg = el.querySelector('svg')
        const name = el.dataset.exportFilename
        if (svg && name) svgToPng(svg, name, palette.card)
      })
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: t('Overview') },
    { id: 'variables', label: t('Per variable') },
    { id: 'quality', label: t('Critical appraisal') },
    { id: 'synthesis', label: t('Synthesis & certainty') },
    { id: 'narrative', label: t('Narrative') },
    { id: 'themes', label: t('Themes') },
  ]

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Results')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-3xl text-sm text-muted-foreground">
        {t('Descriptive synthesis computed live from the extraction table — nothing here is typed in. Charts export as PNG for the manuscript; the CSV carries the same aggregated numbers.')}
      </p>

      {isLoading || !data ? (
        <p className="text-muted-foreground">{t('Loading…')}</p>
      ) : (
        <>
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="mb-4">
            <TabsList>
              {tabs.map((tb) => (
                <TabsTrigger key={tb.id} value={tb.id}>{tb.label}</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          {/* the thematic map works on the whole corpus — it needs no
              included study, so it sits outside the empty-state gate */}
          {tab === 'themes' ? (
            <ThemesTab pid={pid} />
          ) : data.n_included === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            {t('No included study yet — the results are computed over the full-text-included corpus.')}{' '}
            <Link to={`/projects/${pid}/ft-screening`}
                  className="text-foreground underline underline-offset-2">
              {t('Finish full-text screening')}
            </Link>{' '}
            {t('to populate this page.')}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KpiTile label={data.n_studies !== data.n_included
                         ? t('Included studies ({{n}} articles)', { n: data.n_included })
                         : t('Included studies')}
                       value={data.n_studies} />
              <KpiTile label={t('With extraction data')}
                       value={data.n_with_any_value} total={data.n_included}
                       to={`/projects/${pid}/extraction`}
                       linkLabel={t('Extraction')} />
              <KpiTile label={t('Fully validated')}
                       value={data.n_fully_validated} total={data.n_included}
                       to={`/projects/${pid}/extraction`}
                       linkLabel={t('Extraction')} />
              <KpiTile label={t('Appraised')}
                       value={data.jbi.n_appraised} total={data.n_included}
                       to={`/projects/${pid}/extraction?tab=jbi`}
                       linkLabel={t('Appraisal tab')} />
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={exportAllCharts}
                      title={t('Download every chart on this tab as PNG images')}>
                ⤓ {t('All charts')}
              </Button>
              <Button asChild variant="outline" size="sm">
                <a href={`${API(pid)}/export.csv`}>⬇ CSV</a>
              </Button>
            </div>
          </div>

          {!data.extraction_started && (
            <p className="mb-4 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('Extraction has not started yet — the variable distributions fill up as the extraction table is completed.')}
            </p>
          )}

          {/* the cross-filters act on the extraction aggregates; the
              synthesis declaration is not one of them */}
          {tab !== 'narrative' && tab !== 'synthesis' && (
            <FiltersBar data={data} view={view ?? data}
                        filters={filters} onChange={setFilters} />
          )}

          {tab === 'overview' && (
            <OverviewTab pid={pid} full={data} view={view ?? data}
                         filters={filters} onChange={setFilters} />
          )}
          {tab === 'variables' && (
            <VariablesTab full={data} view={view ?? data}
                          filtering={isFiltering(filters)} />
          )}
          {tab === 'quality' && (
            <QualityTab full={data} view={view ?? data}
                        filtering={isFiltering(filters)} />
          )}
          {tab === 'synthesis' && (
            <SynthesisTab pid={pid}
                          isAdmin={project?.my_role === 'admin'} />
          )}
          {tab === 'narrative' && <NarrativePanel pid={pid} />}
        </>
      )}
        </>
      )}
    </div>
  )
}

// ---- Synthesis & certainty --------------------------------------------------------

/** SWiM declaration, the reported results with their GRADE ratings, and the
 * Summary of Findings table the three of them produce. */
function SynthesisTab({ pid, isAdmin }: { pid: number; isAdmin: boolean }) {
  const { data: catalogue } = useQuery<SynthesisCatalogue>({
    queryKey: ['synthesis-catalogue', pid],
    queryFn: () => api.get(`/api/projects/${pid}/synthesis/catalogue`),
    staleTime: Infinity,
  })
  const { data: plan } = useQuery<SynthesisPlanInfo>({
    queryKey: ['synthesis-plan', pid],
    queryFn: () => api.get(`/api/projects/${pid}/synthesis/plan`),
  })
  return (
    <div className="space-y-6">
      <SynthesisPlanPanel pid={pid} isAdmin={isAdmin} catalogue={catalogue} />
      {plan?.enabled && (
        <>
          <OutcomesPanel pid={pid} isAdmin={isAdmin} catalogue={catalogue}
                         framework={plan.certainty_framework} />
          <SofTable pid={pid} />
        </>
      )}
    </div>
  )
}

// ---- KPI tiles --------------------------------------------------------------------

/** Progress-aware stat tile: value over denominator, micro progress bar
 * (neutral ink, green only at 100%), and a link to the screen that moves
 * the number — a "12" only means something next to its "/ 34". */
function KpiTile({ label, value, total, to, linkLabel }: {
  label: string
  value: number
  total?: number
  to?: string
  linkLabel?: string
}) {
  const done = total !== undefined && total > 0 && value >= total
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums tracking-tight text-foreground">
        {value}
        {total !== undefined && (
          <span className="text-sm font-normal text-muted-foreground"> / {total}</span>
        )}
      </div>
      {total !== undefined && total > 0 && (
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted">
          <div className={cn('h-full rounded-full',
                             done ? 'bg-success' : 'bg-foreground/60')}
               style={{ width: `${Math.min(100, (value / total) * 100)}%` }} />
        </div>
      )}
      {to && linkLabel && !done && (
        <Link to={to}
              className="mt-1 inline-block text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
          → {linkLabel}
        </Link>
      )}
    </div>
  )
}

// ---- Cross-filters ----------------------------------------------------------------

const TOP_CHIPS = 6

interface FilterOption<T> {
  id: string
  label: string
  value: T
}

function FiltersBar({ data, view, filters, onChange }: {
  data: ResultsAggregates   // unfiltered: bounds + option lists
  view: ResultsAggregates   // filtered: live count
  filters: ResultsFilters
  onChange: (f: ResultsFilters) => void
}) {
  const { t } = useTranslation()
  const active = isFiltering(filters)
  const { min, max } = data.years
  const range = filters.years ?? [min ?? 0, max ?? 0]
  const hasYears = min !== null && max !== null && min < max
  const hasDesigns = data.designs.length > 1
  const hasCountries = data.countries.counts.length > 1
  if (!hasYears && !hasDesigns && !hasCountries) return null

  // top chips by count; a selected value beyond the top stays visible as a
  // chip, everything else folds into the "+N" popover
  const split = <T,>(opts: FilterOption<T>[], isSel: (v: T) => boolean) => ({
    visible: opts.filter((o, i) => i < TOP_CHIPS || isSel(o.value)),
    overflow: opts.filter((o, i) => i >= TOP_CHIPS && !isSel(o.value)),
  })
  const designOpts: FilterOption<string | null>[] = data.designs.map((d) => ({
    id: d.design ?? '∅',
    label: `${designLabel(d.design)} (${d.n})`,
    value: d.design,
  }))
  const designSel = (v: string | null) => filters.designs.includes(v)
  const designs = split(designOpts, designSel)
  const countryOpts: FilterOption<string>[] = data.countries.counts.map((c) => ({
    id: c.iso3, label: `${c.name} (${c.n})`, value: c.iso3,
  }))
  const countrySel = (v: string) => filters.countries.includes(v)
  const countries = split(countryOpts, countrySel)

  return (
    <Card className="mb-4">
      <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-2.5 py-3">
        {hasYears && (
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">{t('Years')}</span>
            <Slider min={min} max={max} step={1} value={range}
                    onValueChange={(v) => onChange({
                      ...filters,
                      years: v[0] === min && v[1] === max
                        ? null : [v[0], v[1]],
                    })}
                    className="w-44" />
            <span className="text-xs tabular-nums text-muted-foreground">
              {range[0]}–{range[1]}
            </span>
          </div>
        )}
        {hasDesigns && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-muted-foreground">{t('Design')}</span>
            {designs.visible.map((o) => (
              <FilterChip key={o.id} active={designSel(o.value)} label={o.label}
                          onClick={() => onChange({
                            ...filters,
                            designs: toggleIn(filters.designs, o.value),
                          })} />
            ))}
            {designs.overflow.length > 0 && (
              <OverflowMenu overflow={designs.overflow} isSelected={designSel}
                            onToggle={(v) => onChange({
                              ...filters,
                              designs: toggleIn(filters.designs, v),
                            })} />
            )}
          </div>
        )}
        {hasCountries && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-muted-foreground">{t('Country')}</span>
            {countries.visible.map((o) => (
              <FilterChip key={o.id} active={countrySel(o.value)} label={o.label}
                          onClick={() => onChange({
                            ...filters,
                            countries: toggleIn(filters.countries, o.value),
                          })} />
            ))}
            {countries.overflow.length > 0 && (
              <OverflowMenu overflow={countries.overflow} isSelected={countrySel}
                            searchable
                            onToggle={(v) => onChange({
                              ...filters,
                              countries: toggleIn(filters.countries, v),
                            })} />
            )}
          </div>
        )}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            <b className="text-foreground">{view.n_included}</b>
            {' '}/ {t('{{count}} studies', { count: data.n_included })}
          </span>
          {active && (
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs"
                    onClick={() => onChange(NO_FILTERS)}>
              {t('Reset')}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/** "+N ▾" chip opening the rest of a filter axis (with search for long
 * country lists) — keeps the filter card to one line on 20-country reviews. */
function OverflowMenu<T>({ overflow, isSelected, onToggle, searchable }: {
  overflow: FilterOption<T>[]
  isSelected: (v: T) => boolean
  onToggle: (v: T) => void
  searchable?: boolean
}) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const shown = q
    ? overflow.filter((o) => o.label.toLowerCase().includes(q.toLowerCase()))
    : overflow
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button"
                className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:text-foreground">
          +{overflow.length} ▾
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start"
                           className="max-h-72 w-56 overflow-y-auto">
        {searchable && (
          <Input value={q} onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.stopPropagation()}
                 placeholder={t('Search')}
                 className="mb-1 h-7 text-xs" />
        )}
        {shown.map((o) => (
          <DropdownMenuCheckboxItem key={o.id} checked={isSelected(o.value)}
                                    onSelect={(e) => e.preventDefault()}
                                    onCheckedChange={() => onToggle(o.value)}>
            {o.label}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function FilterChip({ label, active, onClick }: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
            className={cn(
              'rounded-full border px-2 py-0.5 text-xs transition-colors',
              active
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border text-muted-foreground hover:text-foreground',
            )}>
      {label}
    </button>
  )
}

// ---- Overview ---------------------------------------------------------------------

function OverviewTab({ pid, full, view, filters, onChange }: {
  pid: number
  full: ResultsAggregates   // unfiltered: ghost-bar denominators
  view: ResultsAggregates   // filtered: the values on display
  filters: ResultsFilters
  onChange: (f: ResultsFilters) => void
}) {
  const { t } = useTranslation()
  const filtering = isFiltering(filters)
  const c = view.countries

  // clicking a year bar pins the range to that year; clicking again clears it
  const activeYear = filters.years && filters.years[0] === filters.years[1]
    ? filters.years[0] : null
  const onSelectYear = (y: number) => onChange({
    ...filters,
    years: activeYear === y ? null : [y, y],
  })

  // designs: categories & order come from the unfiltered corpus so bars never
  // vanish under a filter — the filtered count fills in front of the total
  const viewDesigns = new Map(view.designs.map((d) => [d.design, d.n]))
  const designItems: BarItem[] = full.designs.map((d) => ({
    label: designLabel(d.design),
    n: filtering ? viewDesigns.get(d.design) ?? 0 : d.n,
    total: filtering ? d.n : undefined,
    active: filters.designs.includes(d.design),
    key: JSON.stringify(d.design),
  }))

  const clickHint = t('Click a bar to filter every chart; click it again to clear.')
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={t('Studies per year')} filename="studies-per-year.png"
                   n={view.n_included}
                   nTotal={filtering ? full.n_included : undefined}
                   tableData={view.years.counts.map((y) => ({
                     label: String(y.year), value: y.n,
                   }))}
                   subtitle={view.years.unknown > 0
                     ? t('{{count}} without a year', { count: view.years.unknown })
                     : clickHint}>
          {(view.years.counts.length > 0 ||
            (filtering && full.years.counts.length > 0))
            ? <YearHistogram counts={view.years.counts}
                             totals={filtering ? full.years.counts : undefined}
                             onSelectYear={onSelectYear}
                             activeYear={activeYear}
                             ariaLabel={`${t('Studies per year')} (n=${view.n_included})`} />
            : <EmptyChart />}
        </ChartCard>
        <ChartCard title={t('Study designs')} filename="study-designs.png"
                   n={view.n_included}
                   nTotal={filtering ? full.n_included : undefined}
                   tableData={designItems.map((d) => ({
                     label: d.label,
                     value: d.total !== undefined ? `${d.n} / ${d.total}` : d.n,
                   }))}
                   subtitle={t('Qualified on the extraction table')}>
          <BarChart horizontal items={designItems}
                    ariaLabel={`${t('Study designs')} (n=${view.n_included})`}
                    onSelect={(item) => onChange({
                      ...filters,
                      designs: toggleIn(filters.designs,
                                        JSON.parse(item.key!) as string | null),
                    })} />
        </ChartCard>
      </div>

      <ChartCard
        title={t('Countries')}
        filename="countries-map.png"
        n={c.n_studies_with_country}
        nTotal={filtering ? full.countries.n_studies_with_country : undefined}
        subtitle={c.column_id === null
          ? undefined
          : <>{t('From the “{{name}}” column', { name: c.column_name })}
              {c.n_multi_country > 0 &&
                ' ' + t('— multi-country studies count once per country (n={{count}})', { count: c.n_multi_country })}
              {c.missing > 0 && ` · ${t('{{count}} without a value', { count: c.missing })}`}
              {' · '}{t('Click a country to filter.')}</>}
      >
        {c.column_id === null ? (
          <p className="py-6 text-sm text-muted-foreground">
            {t('No “Country” column in the extraction table — add one (the standard template includes it) in')}{' '}
            <Link to={`/projects/${pid}/extraction`}
                  className="text-foreground underline underline-offset-2">
              {t('Extraction')}
            </Link>{' '}
            {t('to get the map.')}
          </p>
        ) : c.counts.length === 0 && !filtering ? (
          <EmptyChart />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <WorldMap counts={c.counts}
                      selected={filters.countries}
                      onSelect={(iso3) => onChange({
                        ...filters,
                        countries: toggleIn(filters.countries, iso3),
                      })}
                      ariaLabel={`${t('Countries')} (n=${c.n_studies_with_country})`} />
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-sm">
                <tbody>
                  {c.counts.map((x) => (
                    <tr key={x.iso3} className="border-b border-border last:border-0">
                      <td className="py-1 pr-2">{x.name}</td>
                      <td className="py-1 text-right font-medium tabular-nums">{x.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {(c.unmatched.length > 0) && (
          <details className="mt-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs">
            <summary className="cursor-pointer font-medium text-warning">
              {t('Unrecognized country values ({{count}}) — fix them in the extraction table to include them', { count: c.unmatched.length })}
            </summary>
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {c.unmatched.map((u) => (
                <li key={u.value}
                    className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                  “{u.value}” × {u.n}
                </li>
              ))}
            </ul>
          </details>
        )}
      </ChartCard>
    </div>
  )
}

// ---- Per-variable -----------------------------------------------------------------

function VariablesTab({ full, view, filtering }: {
  full: ResultsAggregates
  view: ResultsAggregates
  filtering: boolean
}) {
  const { t } = useTranslation()
  if (view.columns.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('No chartable extraction column yet — choice, multi, yes/no and number columns get an automatic distribution here (free-text columns are synthesized in the narrative instead).')}
      </p>
    )
  }
  const fullById = new Map(full.columns.map((col) => [col.id, col]))
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {view.columns.map((col) => (
        <ColumnCard key={col.id} col={col}
                    fullCol={fullById.get(col.id)} filtering={filtering} />
      ))}
    </div>
  )
}

function ColumnCard({ col, fullCol, filtering }: {
  col: ColumnAggregate
  fullCol?: ColumnAggregate
  filtering: boolean
}) {
  const { t } = useTranslation()
  const notes = [
    col.n_missing > 0 ? t('{{count}} missing', { count: col.n_missing }) : null,
    col.n_conflicts > 0 ? t('{{count}} conflicting (excluded)', { count: col.n_conflicts }) : null,
  ].filter(Boolean).join(' · ')
  const slug = col.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')
  if (col.col_type === 'number') {
    const stats = col.stats
    return (
      <ChartCard title={col.name} filename={`${slug}.png`}
                 n={stats?.n ?? 0}
                 nTotal={filtering ? fullCol?.stats?.n : undefined}
                 tableData={stats ? [
                   { label: t('min'), value: stats.min },
                   { label: t('median'), value: stats.median },
                   { label: t('mean'), value: stats.mean },
                   { label: t('max'), value: stats.max },
                   { label: 'IQR', value: `${stats.q1}–${stats.q3}` },
                 ] : undefined}
                 subtitle={notes || undefined}>
        {!stats ? <EmptyChart /> : (
          <>
            <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
              <span>{t('min')} <b className="text-foreground">{stats.min}</b></span>
              <span>{t('median')} <b className="text-foreground">{stats.median}</b></span>
              <span>{t('mean')} <b className="text-foreground">{stats.mean}</b></span>
              <span>{t('max')} <b className="text-foreground">{stats.max}</b></span>
              <span>IQR <b className="text-foreground">{stats.q1}–{stats.q3}</b></span>
            </div>
            <NumericHistogram values={col.values ?? []} stats={stats}
                              ariaLabel={`${col.name} (n=${stats.n})`} />
          </>
        )}
      </ChartCard>
    )
  }
  // categories & order from the unfiltered corpus so the ghost totals keep
  // the denominator visible while a cross-filter is active
  const dist = col.distribution ?? []
  const fullDist = (filtering ? fullCol?.distribution : undefined) ?? dist
  const byValue = new Map(dist.map((d) => [d.value, d.n]))
  const items: BarItem[] = filtering
    ? fullDist.map((d) => ({
        label: d.value, n: byValue.get(d.value) ?? 0, total: d.n,
      }))
    : dist.map((d) => ({ label: d.value, n: d.n }))
  const n = dist.reduce((s, d) => s + d.n, 0)
  const nTotal = fullDist.reduce((s, d) => s + d.n, 0)
  return (
    <ChartCard title={col.name} filename={`${slug}.png`}
               n={n} nTotal={filtering ? nTotal : undefined}
               tableData={items.map((d) => ({
                 label: d.label,
                 value: d.total !== undefined ? `${d.n} / ${d.total}` : d.n,
               }))}
               subtitle={notes || undefined}>
      {items.length === 0 ? <EmptyChart />
        : <BarChart horizontal items={items}
                    ariaLabel={`${col.name} (n=${n})`} />}
    </ChartCard>
  )
}

// ---- Critical appraisal -----------------------------------------------------------

function QualityTab({ full, view, filtering }: {
  full: ResultsAggregates
  view: ResultsAggregates
  filtering: boolean
}) {
  const { t } = useTranslation()
  const palette = useVizPalette()
  const jbi = view.jbi
  if (jbi.n_appraised === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('No appraisal yet — assess the studies on the extraction page (Appraisal tab) to get this synthesis.')}
      </p>
    )
  }
  // fixed segment order + explicit labels; 'unclear' and 'n/a' carry their
  // identity through shape (hatching / dashed outline), not color alone —
  // both stay readable in dark theme, B&W print and under any CVD
  const segments = [
    { label: t('yes'), color: palette.teal },
    { label: t('no'), color: palette.orange },
    { label: t('unclear'), color: palette.mutedForeground, pattern: 'hatch' as const },
    { label: t('n/a'), color: palette.mutedForeground, pattern: 'hollow' as const },
  ]
  const pooledValues = jbi.per_study.reduce<number[]>((acc, s) => {
    acc[0] += s.answers.yes
    acc[1] += s.answers.no
    acc[2] += s.answers.unclear
    acc[3] += s.answers.na
    return acc
  }, [0, 0, 0, 0])
  const answerRow = (a: { yes: number; no: number; unclear: number; na: number }) =>
    `${t('yes')} ${a.yes} · ${t('no')} ${a.no} · ${t('unclear')} ${a.unclear} · ${t('n/a')} ${a.na}`
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-8">
        <Stat value={jbi.n_appraised} label={t('Studies appraised')} />
        {jbi.dual && (
          <Stat value={jbi.n_from_consensus}
                label={t('Settled by two assessors')} />
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {t('Instrument:')}{' '}
        <span className="text-foreground">{t(jbi.instrument.label)}</span>
        {jbi.instrument.citation && ` — ${jbi.instrument.citation}`}
        {jbi.dual
          ? ` · ${t('Two independent assessors; the appraisal they settled on is the one counted here.')}`
          : ` · ${t('Single assessor — no independent duplicate appraisal.')}`}
      </p>

      {/* The headline: judgement per bias domain. A single "% of criteria met"
          is the composite quality score JBI and the Cochrane Handbook both
          advise against reading as a ranking, so it sits further down. */}
      {jbi.by_domain.map((block) => (
        <ChartCard key={block.design}
                   title={block.granularity === 'domain'
                     ? t('Risk of bias by domain — {{design}}', { design: designLabel(block.design) })
                     : t('Answers per checklist item — {{design}}', { design: designLabel(block.design) })}
                   filename={`appraisal-domains-${block.design}.png`}
                   n={block.n_studies}
                   tableData={block.rows.map((r) => ({
                     label: r.label, value: answerRow(r.counts),
                   }))}
                   subtitle={block.granularity === 'domain'
                     ? t('Answers pooled across the domain’s questions and across studies')
                     : t('This checklist groups its questions in no domain, so each item is shown on its own')}>
          <StackedBar
            rows={block.rows.map((r) => ({
              label: r.label,
              values: [r.counts.yes, r.counts.no, r.counts.unclear, r.counts.na],
            }))}
            segments={segments}
            ariaLabel={`${designLabel(block.design)} (n=${block.n_studies})`}
          />
        </ChartCard>
      ))}

      <ChartCard title={t('Checklist answers per study')}
                 filename="jbi-per-study.png" n={jbi.n_appraised}
                 nTotal={filtering ? full.jbi.n_appraised : undefined}
                 tableData={jbi.per_study.map((s) => ({
                   label: s.label, value: answerRow(s.answers),
                 }))}
                 subtitle={t('Answers pooled across assessors, best-rated first')}>
        <StackedBar
          rows={jbi.per_study.map((s) => ({
            label: s.label,
            values: [s.answers.yes, s.answers.no, s.answers.unclear, s.answers.na],
          }))}
          pooled={{
            label: t('All studies ({{count}})', { count: jbi.n_appraised }),
            values: pooledValues,
          }}
          segments={segments}
          ariaLabel={`${t('Checklist answers per study')} (n=${jbi.n_appraised})`}
        />
      </ChartCard>
      {/* an instrument that forbids a score (MMAT) gets no "% met" chart at
          all — the per-domain and per-item views above are the appraisal */}
      {jbi.instrument.score && jbi.by_design.length > 0 && (
        <ChartCard title={t('Share of criteria met, by design')}
                   filename="jbi-by-design.png"
                   tableData={jbi.by_design.map((d) => ({
                     label: designLabel(d.design),
                     value: `${Math.round(d.avg_pct_yes * 100)}% (${d.n_studies})`,
                   }))}
                   subtitle={t('A completeness figure, not a quality ranking: two studies failing different criteria score the same. Read the domains above for what actually differs.')}>
          <BarChart horizontal color={palette.teal}
                    ariaLabel={t('Share of criteria met, by design')}
                    items={jbi.by_design.map((d) => ({
                      label: designLabel(d.design),
                      n: Math.round(d.avg_pct_yes * 100),
                      title: `${designLabel(d.design)} — ` +
                             t('{{pct}}% yes ({{count}} studies)',
                               { pct: Math.round(d.avg_pct_yes * 100), count: d.n_studies }),
                    }))} />
        </ChartCard>
      )}
    </div>
  )
}

function EmptyChart() {
  const { t } = useTranslation()
  return (
    <p className="py-6 text-sm text-muted-foreground">
      {t('No extraction data yet for this chart.')}
    </p>
  )
}
