// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Check, ChevronsUpDown, Clock, Database, Download, FileDown, FolderKanban, FolderSync,
  HardDriveDownload, KeyRound, LibraryBig, LogOut, MessageSquareWarning,
  NotebookPen, Plug, Scale, Settings, Sparkles, Tags, Trash2, UserCheck, Users,
} from 'lucide-react'
import { api, type Project, type User } from '@/api'
import { cn } from '@/lib/utils'
import FulltextLibrary from './FulltextLibrary'
import SourceNotice from './SourceNotice'
import ChangePasswordDialog from './ChangePasswordDialog'
import ExportReferencesDialog from './ExportReferences'
import { isSandbox, useInstance } from './DemoBanner'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from './ui/dropdown-menu'

// The whole review pipeline; steps without a path are not implemented yet.
export const STEPS: { id: string; label: string; path?: string }[] = [
  { id: 'protocol', label: 'Protocol', path: 'protocol' },
  { id: 'equations', label: 'Equations', path: 'equations' },
  { id: 'search', label: 'Search', path: 'search' },
  { id: 'dedup', label: 'Dedup', path: 'dedup' },
  { id: 'screening', label: 'Screening', path: 'screening' },
  { id: 'fulltext', label: 'FT retrieval', path: 'fulltext' },
  { id: 'ft-screening', label: 'FT screening', path: 'ft-screening' },
  { id: 'snowballing', label: 'Snowballing', path: 'snowballing' },
  { id: 'extraction', label: 'Extraction', path: 'extraction' },
  { id: 'results', label: 'Results', path: 'results' },
  { id: 'prisma', label: 'PRISMA', path: 'prisma' },
  { id: 'reporting', label: 'Reporting', path: 'reporting' },
]

interface RoundState {
  round: number
  status: 'draft' | 'active'
  eligible: number
  decided: number
  done: boolean
}
interface Progress {
  current: string
  done: string[]
  rounds: { ta: RoundState[]; ft: RoundState[] }
}

const SPACE_NAV = [
  { to: '/', label: 'Projects', icon: FolderKanban },
  // standalone module: pasted DOIs → PDF/zip, outside any project. Only shown
  // to the users the superadmin granted it to (Administration → Users).
  { to: '/download-papers', label: 'Download papers', icon: Download },
  // personal, browser-held library credentials — every member has some
  { to: '/settings/institutions', label: 'My institutional access', icon: LibraryBig },
  // personal reference-manager key (Zotero), server-stored and encrypted
  { to: '/settings/integrations', label: 'My integrations', icon: Plug },
] as const

// app-wide settings: global AI + database keys, app-admin territory
const ADMIN_NAV = [
  // registered users + the per-user modules the superadmin grants them
  { to: '/settings/users', label: 'Users', icon: Users },
  { to: '/settings/llm', label: 'AI keys (app)', icon: Sparkles },
  { to: '/settings/databases', label: 'Database keys', icon: Database },
  // server-stored proxies inherited by every project (personal ones are in
  // the workspace section — they never leave the browser)
  { to: '/settings/institutions-app', label: 'Institutional access (app)',
    icon: LibraryBig },
  { to: '/settings/backup', label: 'Instance backup', icon: HardDriveDownload },
] as const

export default function AppSidebar({ user }: { user: User }) {
  const { t } = useTranslation()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [showLibrary, setShowLibrary] = useState(false)
  const [showExport, setShowExport] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const match = location.pathname.match(/^\/projects\/(\d+)/)
  const projectId = match ? Number(match[1]) : null
  const currentSeg = location.pathname.split('/')[3] // /projects/:id/<seg>

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === projectId)

  const { data: progress } = useQuery<Progress>({
    queryKey: ['project-progress', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/progress`),
    enabled: projectId !== null,
    staleTime: 15_000,
  })

  const { data: instance } = useInstance()
  const { data: ticketSummary } = useQuery<{ open: number }>({
    queryKey: ['tickets-summary'],
    queryFn: () => api.get('/api/tickets/summary'),
    refetchInterval: 30_000,
  })
  const openTickets = ticketSummary?.open ?? 0

  const logout = async () => {
    // a guest session has no password: once signed out, nobody gets back in
    if (user.is_guest && !confirm(t('Sign out of this guest session? You will not be able to come back to it; its data is deleted at the next daily reset.'))) return
    await api.post('/api/auth/logout')
    queryClient.setQueryData(['me'], null)
  }
  // demo visitors: no sync, no stored keys or institutional logins, no
  // standalone downloads — the backend refuses them, so don't offer them
  const sandbox = isSandbox(user, instance)
  const endGuestSession = async () => {
    if (!confirm(t('Delete this demo session and everything in it now? This cannot be undone.'))) return
    await api.del('/api/auth/guest')
    queryClient.clear()
    queryClient.setQueryData(['me'], null)
  }

  const roundGroups = ([
    ['ta', 'Screening', 'screening'],
    ['ft', 'FT screening', 'ft-screening'],
  ] as const)
    .map(([stage, label, page]) => ({
      stage, label, page,
      rounds: (progress?.rounds[stage] ?? []).filter((r) => r.round >= 2),
    }))
    .filter((g) => g.rounds.length > 0)

  const initials = (user.display_name || '?')
    .split(/\s+/).map((s) => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-border bg-background" aria-label={t('Sidebar')}>
      {/* brand */}
      <div className="flex items-center gap-2.5 px-4 py-3.5">
        <Link to="/" className="flex size-6 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
          L
        </Link>
        <span className="font-semibold tracking-tight">LitUbik</span>
      </div>

      {/* project switcher */}
      {project && (
        <div className="px-3 pb-2">
          <DropdownMenu>
            <DropdownMenuTrigger className="flex w-full items-center gap-2 rounded-md border border-border bg-card px-2.5 py-2 text-left text-sm font-medium transition-colors hover:bg-accent outline-none focus-visible:ring-ring/50 focus-visible:ring-[3px]">
              <span className="size-4 shrink-0 rounded bg-muted ring-1 ring-inset ring-border" />
              <span className="min-w-0 flex-1 truncate">{project.name}</span>
              {project.sync_role === 'satellite' && (
                <span
                  className="shrink-0 rounded-full bg-warning/15 px-1.5 text-xs font-semibold text-warning"
                  title={t('Satellite copy — structural state managed by the coordinator')}
                >
                  sat
                </span>
              )}
              <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-56">
              <DropdownMenuLabel>{t('Projects')}</DropdownMenuLabel>
              {projects.map((p) => (
                <DropdownMenuItem key={p.id} asChild>
                  <Link to={`/projects/${p.id}/${currentSeg || 'protocol'}`}>
                    <span className="flex-1 truncate">{p.name}</span>
                    {p.id === projectId && <Check className="size-4" />}
                  </Link>
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link to="/">{t('All projects…')}</Link>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      {/* nav / pipeline */}
      <nav className="flex-1 overflow-y-auto px-3 pb-2" aria-label={t('Main navigation')}>
        {projectId ? (
          <>
            <p className="px-2 pb-1 pt-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
              {t('Pipeline')}
            </p>
            <ul data-tour="pipeline" className="flex flex-col gap-0.5">
              {STEPS.map((step, i) => {
                const isCurrent = progress?.current === step.id
                const isDone = progress?.done.includes(step.id)
                const active = currentSeg === step.path
                if (!step.path) {
                  return (
                    <li key={step.id}>
                      <span className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground/50">
                        <StepIndex n={i + 1} state="soon" />
                        {t(step.label)}
                      </span>
                    </li>
                  )
                }
                return (
                  <li key={step.id}>
                    <Link
                      to={`/projects/${projectId}/${step.path}`}
                      className={cn(
                        'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                        active
                          ? 'bg-accent font-medium text-foreground shadow-[inset_2px_0_0_var(--primary)]'
                          : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                      )}
                    >
                      <StepIndex n={i + 1} state={isDone ? 'done' : active ? 'active' : 'todo'} />
                      <span className="flex-1 truncate">{t(step.label)}</span>
                      {isCurrent && !active && (
                        <span className="size-1.5 shrink-0 rounded-full bg-warning" aria-label={t('current step')} />
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>

            {roundGroups.length > 0 && (
              <div className="mt-3 rounded-md border border-border bg-card px-2.5 py-2">
                <p className="pb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  ❄ {t('Snowballing')}
                </p>
                <div className="flex flex-col gap-1.5">
                  {roundGroups.map((g) => (
                    <div key={g.stage} className="flex flex-wrap items-center gap-1">
                      <span className="mr-1 text-xs text-muted-foreground">{t(g.label)}</span>
                      {g.rounds.map((r) => (
                        <Link
                          key={r.round}
                          to={`/projects/${projectId}/${g.page}?round=${r.round}`}
                          title={r.done
                            ? t('{{label}} round {{round}} — completed',
                                { label: t(g.label), round: r.round })
                            : t('{{label}} round {{round}} — {{decided}}/{{eligible}} decided',
                                { label: t(g.label), round: r.round,
                                  decided: r.decided, eligible: r.eligible })}
                          className={cn(
                            'rounded-full px-2 py-0.5 text-xs font-medium tabular-nums transition-colors',
                            r.done
                              ? 'bg-muted text-muted-foreground hover:text-foreground'
                              : r.status === 'active'
                                ? 'bg-warning/15 text-warning hover:bg-warning/25'
                                : 'border border-dashed border-border text-muted-foreground hover:text-foreground',
                          )}
                        >
                          {r.done ? '✓ ' : ''}r{r.round}
                          {r.status === 'active' && !r.done ? ` · ${r.decided}/${r.eligible}` : ''}
                        </Link>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button
              onClick={() => setShowLibrary(true)}
              className="mt-3 flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <LibraryBig className="size-4" /> {t('Downloaded PDFs')}
            </button>
            <button
              onClick={() => setShowExport(true)}
              title={t('Export the references (RIS, BibTeX, CSV) at any stage — all, included, excluded or undecided')}
              className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <FileDown className="size-4" /> {t('Export references')}
            </button>
            <Link
              to={`/projects/${projectId}/tags`}
              className={cn(
                'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                currentSeg === 'tags'
                  ? 'bg-accent font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <Tags className="size-4" /> {t('Tagged papers')}
            </Link>
            <Link
              to={`/projects/${projectId}/notes`}
              className={cn(
                'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                currentSeg === 'notes'
                  ? 'bg-accent font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <NotebookPen className="size-4" /> {t('Screening notes')}
            </Link>
            {!sandbox && <Link
              to={`/projects/${projectId}/sync`}
              data-tour="sync"
              className={cn(
                'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                currentSeg === 'sync'
                  ? 'bg-accent font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <FolderSync className="size-4" /> {t('Synchronisation')}
              {project?.sync_role === 'satellite' && (
                <span className="ml-auto rounded-full bg-warning/15 px-1.5 text-xs font-semibold text-warning">
                  sat
                </span>
              )}
            </Link>}
            {project?.my_role === 'admin' && (
              <Link
                to={`/projects/${projectId}/settings`}
                data-tour="settings"
                className={cn(
                  'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                  currentSeg === 'settings'
                    ? 'bg-accent font-medium text-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
              >
                <Settings className="size-4" /> {t('Settings')}
              </Link>
            )}
            {project?.my_role === 'admin' && (
              <Link
                to={`/projects/${projectId}/worktime`}
                className={cn(
                  'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                  currentSeg === 'worktime'
                    ? 'bg-accent font-medium text-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
              >
                <Clock className="size-4" /> {t('Work time')}
              </Link>
            )}
          </>
        ) : null}

        <p className="px-2 pb-1 pt-4 text-xs font-bold uppercase tracking-wider text-muted-foreground">
          {t('Workspace')}
        </p>
        <ul className="flex flex-col gap-0.5">
          {SPACE_NAV.filter((item) => !sandbox && (item.to !== '/download-papers'
            || user.is_admin || user.can_download_papers)).map((item) => {
            const active = location.pathname === item.to
            const Icon = item.icon
            return (
              <li key={item.to}>
                <Link
                  to={item.to}
                  className={cn(
                    'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                    active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                >
                  <Icon className="size-4" /> {t(item.label)}
                </Link>
              </li>
            )
          })}
          <li>
            <Link
              to="/tickets"
              className={cn(
                'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                location.pathname === '/tickets' ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <MessageSquareWarning className="size-4" /> {t('Tickets')}
              {openTickets > 0 && (
                <span className="ml-auto rounded-full bg-warning/15 px-1.5 text-xs font-semibold tabular-nums text-warning">
                  {openTickets}
                </span>
              )}
            </Link>
          </li>
        </ul>

        {user.is_admin && (
          <>
            <p className="px-2 pb-1 pt-4 text-xs font-bold uppercase tracking-wider text-muted-foreground">
              {t('Administration')}
            </p>
            <ul className="flex flex-col gap-0.5">
              {[...ADMIN_NAV,
                // M6: allowlist page only makes sense on a demo instance
                ...(instance?.demo
                  ? [{ to: '/settings/demo-access', label: 'Demo access',
                       icon: UserCheck }] as const
                  : []),
                // legal pages: published by a demo instance, or once written
                ...(instance?.demo || (instance?.legal ?? []).length > 0
                  ? [{ to: '/settings/legal', label: 'Legal pages',
                       icon: Scale }] as const
                  : [])].map((item) => {
                const active = location.pathname === item.to
                const Icon = item.icon
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      className={cn(
                        'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                        active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                      )}
                    >
                      <Icon className="size-4" /> {t(item.label)}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </nav>

      {/* user */}
      <div className="border-t border-border p-2">
        <DropdownMenu>
          <DropdownMenuTrigger className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-accent outline-none focus-visible:ring-ring/50 focus-visible:ring-[3px]">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold ring-1 ring-inset ring-border">
              {initials}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{user.display_name}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {user.is_guest ? t('Guest session') : t('Signed in')}
              </span>
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="top" className="w-52">
            <DropdownMenuLabel>{user.display_name}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {!user.is_guest && (
              <DropdownMenuItem onClick={() => setShowPassword(true)}>
                <KeyRound className="size-4" /> {t('Change password')}
              </DropdownMenuItem>
            )}
            {sandbox && (
              <DropdownMenuItem onClick={endGuestSession}
                                className="text-destructive focus:text-destructive">
                <Trash2 className="size-4" /> {t('End session and delete my data')}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={logout} className="text-destructive focus:text-destructive">
              <LogOut className="size-4" /> {t('Sign out')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <SourceNotice />

      <ChangePasswordDialog open={showPassword} onOpenChange={setShowPassword} />

      {showLibrary && projectId && (
        <FulltextLibrary projectId={projectId} onClose={() => setShowLibrary(false)} />
      )}
      {projectId && (
        <ExportReferencesDialog projectId={projectId} open={showExport}
                                onOpenChange={setShowExport} />
      )}
    </aside>
  )
}

function StepIndex({ n, state }: { n: number; state: 'done' | 'active' | 'todo' | 'soon' }) {
  return (
    <span
      className={cn(
        'flex size-5 shrink-0 items-center justify-center rounded-md text-xs font-bold tabular-nums',
        state === 'active' && 'bg-primary text-primary-foreground',
        state === 'done' && 'text-foreground',
        state === 'todo' && 'bg-muted text-muted-foreground',
        state === 'soon' && 'bg-muted/50 text-muted-foreground/60',
      )}
    >
      {state === 'done' ? <Check className="size-3.5" strokeWidth={3} /> : n}
    </span>
  )
}
