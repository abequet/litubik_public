// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

const API = (pid: number) => `/api/projects/${pid}/reporting/checklists`

interface Row {
  number: string
  section: string
  text: string
  status: 'evidenced' | 'author' | 'not_done' | 'n_a'
  fact: string
  page_ref: string
  note: string
  overridden: boolean
}

interface Checklist {
  key: string
  label: string
  citation: string
  rows: Row[]
}

interface Trigger {
  key: string
  domain: string
  severity: 'blocking' | 'advisory'
  message: string
}

interface Report {
  checklists: Checklist[]
  triggers: Trigger[]
  triggers_citation: string
  statuses: string[]
}

const STATUS_LABEL: Record<Row['status'], string> = {
  evidenced: 'Recorded by the app',
  author: 'Yours to write',
  not_done: 'Not done',
  n_a: 'Not applicable',
}

const STATUS_TONE: Record<Row['status'], string> = {
  evidenced: 'border-success/40 bg-success/10 text-success',
  author: 'border-border bg-muted text-muted-foreground',
  not_done: 'border-warning/40 bg-warning/10 text-warning',
  n_a: 'border-border bg-muted text-muted-foreground',
}

/** The reporting checklists, each item answered by what the pipeline recorded.
 *
 * The point is the "Not done" state. An empty checklist cell reads as an
 * oversight; "not done" reads as a finding — and it is the difference between
 * a filled checklist and a claimed one, which is exactly what editorial triage
 * penalises. */
export default function ChecklistsPanel({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const [active, setActive] = useState<string | null>(null)
  const { data } = useQuery<Report>({
    queryKey: ['checklists', pid],
    queryFn: () => api.get(API(pid)),
  })

  if (!data) return <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
  const current = data.checklists.find((c) => c.key === active)
    ?? data.checklists[0]

  return (
    <div className="max-w-4xl space-y-4">
      <p className="text-sm text-muted-foreground">
        {t('Editors query reviews that declare compliance with a standard instead of showing it. LitUbik watched this review happen, so it answers what it can with facts — and says plainly where a stage never ran. Add your page numbers and the items only you can write, then export the file your journal asks for.')}
      </p>

      {data.triggers.length > 0 && (
        <Card className="border-warning/40 p-4">
          <h2 className="text-sm font-semibold text-foreground">
            {t('Before you submit')}
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {t('The problems editorial triage looks for, when they are present. These are not scores — a grade is the editor\'s judgement, not a property of your project.')}
          </p>
          <ul className="mt-3 space-y-2">
            {data.triggers.map((trigger) => (
              <li key={trigger.key} className="text-sm">
                <span className={cn('mr-2 rounded border px-1.5 py-0.5 text-xs',
                  trigger.severity === 'blocking'
                    ? 'border-destructive/40 bg-destructive/10 text-destructive'
                    : 'border-warning/40 bg-warning/10 text-warning')}>
                  {t(trigger.severity === 'blocking'
                    ? 'usually prohibitive' : 'worth checking')}
                </span>
                <span className="text-muted-foreground">
                  <span className="text-foreground">{t(trigger.domain)}</span>
                  {' — '}{trigger.message}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card className="p-4">
        {data.checklists.length > 1 && (
          <Tabs value={current.key} onValueChange={setActive} className="mb-3">
            <TabsList>
              {data.checklists.map((c) => (
                <TabsTrigger key={c.key} value={c.key}>{c.label}</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        )}

        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <p className="max-w-2xl text-xs text-muted-foreground">{current.citation}</p>
          <Button asChild variant="outline" size="sm">
            <a href={`${API(pid)}/${current.key}.csv`}>⬇ CSV</a>
          </Button>
        </div>

        <ul className="space-y-1">
          {current.rows.map((row) => (
            <ChecklistRow key={row.number} pid={pid} checklist={current.key}
                          row={row} statuses={data.statuses} />
          ))}
        </ul>
      </Card>
    </div>
  )
}


function ChecklistRow({ pid, checklist, row, statuses }: {
  pid: number
  checklist: string
  row: Row
  statuses: string[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [pageRef, setPageRef] = useState(row.page_ref)
  const [note, setNote] = useState(row.note)

  const save = useMutation({
    mutationFn: (statusOverride?: string) => api.put(`${API(pid)}/answer`, {
      checklist, item: row.number, page_ref: pageRef, note,
      status_override: statusOverride ?? (row.overridden ? row.status : ''),
    }),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['checklists', pid] }),
  })

  return (
    <li className="rounded-md border border-border p-2">
      <button onClick={() => setOpen(!open)}
              className="flex w-full items-start gap-2 text-left">
        <span className="w-10 shrink-0 font-mono text-xs text-muted-foreground">
          {row.number}
        </span>
        <span className="min-w-0 flex-1 text-xs text-foreground">{row.text}</span>
        <span className={cn('shrink-0 rounded border px-1.5 py-0.5 text-xs',
          STATUS_TONE[row.status])}>
          {t(STATUS_LABEL[row.status])}
        </span>
      </button>

      {row.fact && (
        <p className="mt-1 pl-12 text-xs text-muted-foreground">{row.fact}</p>
      )}

      {open && (
        <div className="mt-2 space-y-2 pl-12">
          <div className="flex gap-2">
            <Input className="max-w-[12rem]" value={pageRef}
                   placeholder={t('Page, section…')}
                   onChange={(e) => setPageRef(e.target.value)} />
            <Button size="sm" onClick={() => save.mutate(undefined)}>
              {t('Save')}
            </Button>
          </div>
          <Textarea rows={2} value={note}
                    placeholder={t('What you report for this item')}
                    onChange={(e) => setNote(e.target.value)} />
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">
              {t('Override the status:')}
            </span>
            {statuses.map((s) => (
              <button key={s} type="button"
                      onClick={() => save.mutate(s)}
                      className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent">
                {t(STATUS_LABEL[s as Row['status']] ?? s)}
              </button>
            ))}
            {row.overridden && (
              <button type="button" onClick={() => save.mutate('')}
                      className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent">
                {t('Back to what the app found')}
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  )
}
