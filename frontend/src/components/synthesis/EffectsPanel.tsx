// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, type EffectMeasures, type EffectStudy, type EffectTable,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useVizPalette } from '@/components/results/palette'
import { svgToPng } from '@/components/results/exportPng'
import LiveStatus from '@/components/LiveStatus'

const API = (pid: number) => `/api/projects/${pid}/synthesis`
const NONE = '__none__'

/** Effect sizes per study for one outcome (chantier 10): pick the measure,
 * map its inputs to numeric extraction columns, read each study's estimate
 * with its 95 % CI (table + forest plot without a pooled diamond), and take
 * the data to R/metafor or RevMan Web. LitUbik never pools. */
export default function EffectsPanel({ pid, outcomeId, isAdmin }: {
  pid: number
  outcomeId: number
  isAdmin: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: catalogue } = useQuery<EffectMeasures>({
    queryKey: ['effect-measures', pid],
    queryFn: () => api.get(`${API(pid)}/effects/measures`),
  })
  const { data: table } = useQuery<EffectTable>({
    queryKey: ['effects', pid, outcomeId],
    queryFn: () => api.get(`${API(pid)}/outcomes/${outcomeId}/effects`),
  })
  const [measure, setMeasure] = useState<string>('')
  const [mapping, setMapping] = useState<Record<string, number | null>>({})
  const [error, setError] = useState('')
  useEffect(() => {
    if (!table) return
    setMeasure(table.measure ?? '')
    setMapping(Object.fromEntries(Object.entries(table.mapping)
      .map(([role, m]) => [role, m.column_id])))
  }, [table?.measure, table?.outcome_id])  // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => api.put<EffectTable>(`${API(pid)}/outcomes/${outcomeId}/effects`,
      { measure, mapping }),
    onSuccess: (r) => {
      setError('')
      queryClient.setQueryData(['effects', pid, outcomeId], r)
      queryClient.invalidateQueries({ queryKey: ['synthesis-outcomes', pid] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  const chosen = catalogue?.measures.find((m) => m.key === measure)
  const roles = chosen?.roles ?? []
  const computed = (table?.studies ?? []).filter((s) => s.yi !== undefined)

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {t('Each study gets an estimate and a 95% confidence interval from the extraction cells you map below, computed as metafor\'s escalc() does. LitUbik does not pool them: export the table and run the model you justify, in R or RevMan Web.')}
      </p>
      {isAdmin && catalogue && (
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground"
                   htmlFor={`measure-${outcomeId}`}>{t('Measure')}</label>
            <Select value={measure || NONE}
                    onValueChange={(v) => { setMeasure(v === NONE ? '' : v); setMapping({}) }}>
              <SelectTrigger id={`measure-${outcomeId}`} className="h-8 w-72 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>{t('— not quantitative —')}</SelectItem>
                {catalogue.measures.map((m) => (
                  <SelectItem key={m.key} value={m.key}>{m.key} — {t(m.label)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {roles.map((role) => (
            <div key={role}>
              <label className="mb-1 block text-xs text-muted-foreground"
                     htmlFor={`role-${outcomeId}-${role}`}>
                {t(catalogue.role_labels[role] ?? role)}
              </label>
              <Select value={mapping[role] != null ? String(mapping[role]) : NONE}
                      onValueChange={(v) => setMapping({ ...mapping, [role]: v === NONE ? null : Number(v) })}>
                <SelectTrigger id={`role-${outcomeId}-${role}`} className="h-8 w-44 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>—</SelectItem>
                  {catalogue.columns.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
            {t('Compute')}
          </Button>
          {catalogue.columns.length === 0 && (
            <span className="text-xs text-muted-foreground">
              {t('No numeric extraction column yet — add the N / mean / SD or events columns to the extraction table first.')}
            </span>
          )}
        </div>
      )}
      <LiveStatus className="text-xs">{error}</LiveStatus>

      {table?.measure && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>
              {t('{{measure}} · {{computed}} of {{n}} studies computed', {
                measure: table.measure, computed: table.n_computed, n: table.n_studies })}
              {table.missing_roles.length > 0 && ` · ${t('unmapped: {{roles}}', {
                roles: table.missing_roles.map((r) => t(table.role_labels[r] ?? r)).join(', ') })}`}
            </span>
            <span className="flex-1" />
            <Button asChild variant="outline" size="sm" className="h-7 text-xs">
              <a href={`${API(pid)}/outcomes/${outcomeId}/export/metafor.zip`}>⬇ R / metafor</a>
            </Button>
            <Button asChild variant="outline" size="sm" className="h-7 text-xs">
              <a href={`${API(pid)}/outcomes/${outcomeId}/export/revman.csv`}>⬇ RevMan Web CSV</a>
            </Button>
          </div>
          <EffectsTable table={table} />
          {computed.length > 0 && <ForestPlot table={table} studies={computed} />}
          <p className="text-xs text-muted-foreground">
            {t('RevMan Web generates its own import template per review: match this file\'s columns to that template (one row per arm, the Study ID equal to the included study\'s) before importing.')}
          </p>
        </>
      )}
    </div>
  )
}

const fmt = (v: number | undefined, digits = 2) =>
  v === undefined || Number.isNaN(v) ? '' : v.toFixed(digits)

function EffectsTable({ table }: { table: EffectTable }) {
  const { t } = useTranslation()
  const est = table.log_scale || table.kind === 'correlation'
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">{t('Effect size per study with its 95% confidence interval')}</caption>
        <thead>
          <tr className="text-left text-muted-foreground">
            <th scope="col" className="py-1 pr-3">{t('Study')}</th>
            {table.roles.map((r) => (
              <th scope="col" key={r} className="py-1 pr-3 text-right">{t(table.role_labels[r] ?? r)}</th>
            ))}
            <th scope="col" className="py-1 pr-3 text-right">yi</th>
            <th scope="col" className="py-1 pr-3 text-right">vi</th>
            <th scope="col" className="py-1 pr-3 text-right">
              {est ? t('Estimate [95% CI]') : t('95% CI')}
            </th>
          </tr>
        </thead>
        <tbody>
          {table.studies.map((s) => (
            <tr key={s.study_id} className="border-t border-border">
              <td className="py-1 pr-3 text-foreground">{s.label}</td>
              {table.roles.map((r) => (
                <td key={r} className="py-1 pr-3 text-right tabular-nums">
                  {s.raw[r] ?? <span className="text-destructive">—</span>}
                </td>
              ))}
              {s.yi !== undefined ? (
                <>
                  <td className="py-1 pr-3 text-right tabular-nums">{fmt(s.yi, 4)}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{fmt(s.vi, 4)}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">
                    {est ? `${fmt(s.estimate)} [${fmt(s.estimate_low)}, ${fmt(s.estimate_high)}]`
                         : `[${fmt(s.ci_low)}, ${fmt(s.ci_high)}]`}
                  </td>
                </>
              ) : (
                <td colSpan={3} className="py-1 pr-3 text-destructive">
                  {s.problems.join('; ')}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Forest plot of the per-study estimates — deliberately without a pooled
 * diamond: the pooling is the reader's analysis, not LitUbik's. */
function ForestPlot({ table, studies }: { table: EffectTable; studies: EffectStudy[] }) {
  const { t } = useTranslation()
  const pal = useVizPalette()
  const log = table.log_scale
  const xOf = (v: number) => (log ? Math.log(v) : v)
  const lows = studies.map((s) => xOf(s.estimate_low!))
  const highs = studies.map((s) => xOf(s.estimate_high!))
  let min = Math.min(...lows, log ? 0 : 0), max = Math.max(...highs, log ? 0 : 0)
  if (max - min < 1e-9) { min -= 1; max += 1 }
  const pad = (max - min) * 0.08
  min -= pad; max += pad
  const W = 560, labelW = 170, rowH = 22, top = 24, bottom = 30
  const plotW = W - labelW - 20
  const H = top + studies.length * rowH + bottom
  const x = (v: number) => labelW + ((v - min) / (max - min)) * plotW
  const nullX = x(0)
  const ticks = [min + pad, (min + max) / 2, max - pad]
  const tickLabel = (v: number) => (log ? Math.exp(v) : v).toFixed(2)
  const filename = `forest_${table.outcome_id}.png`
  return (
    <div data-export-filename={filename}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
           aria-label={t('Forest plot: one line per study, point estimate and 95% confidence interval, no pooled estimate')}
           style={{ maxWidth: W, fontFamily: 'system-ui, sans-serif' }}>
        <line x1={nullX} x2={nullX} y1={top - 6} y2={H - bottom + 4}
              stroke={pal.mutedForeground} strokeDasharray="3 3" />
        {studies.map((s, i) => {
          const cy = top + i * rowH + rowH / 2
          const lo = x(xOf(s.estimate_low!)), hi = x(xOf(s.estimate_high!))
          const c = x(xOf(s.estimate!))
          const size = Math.max(3, Math.min(8, 2 + 1.5 / Math.sqrt(s.vi!)))
          return (
            <g key={s.study_id}>
              <text x={labelW - 8} y={cy + 4} textAnchor="end" fontSize="11"
                    fill={pal.foreground}>{s.label.slice(0, 28)}</text>
              <line x1={lo} x2={hi} y1={cy} y2={cy} stroke={pal.foreground} strokeWidth="1.2" />
              <rect x={c - size} y={cy - size} width={size * 2} height={size * 2}
                    fill={pal.blue} />
            </g>
          )
        })}
        {ticks.map((tv, i) => (
          <g key={i}>
            <line x1={x(tv)} x2={x(tv)} y1={H - bottom + 4} y2={H - bottom + 8}
                  stroke={pal.mutedForeground} />
            <text x={x(tv)} y={H - bottom + 20} textAnchor="middle" fontSize="10"
                  fill={pal.mutedForeground}>{tickLabel(tv)}</text>
          </g>
        ))}
        <text x={labelW + plotW / 2} y={H - 2} textAnchor="middle" fontSize="10"
              fill={pal.mutedForeground}>
          {table.measure}{log ? ` (${t('log scale')})` : ''}
        </text>
      </svg>
      <Button variant="outline" size="sm" className="mt-1 h-7 text-xs"
              onClick={(e) => {
                const svg = (e.currentTarget.parentElement as HTMLElement).querySelector('svg')
                if (svg) svgToPng(svg, filename, pal.card)
              }}>
        ⤓ PNG
      </Button>
    </div>
  )
}
