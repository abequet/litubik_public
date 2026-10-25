// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Menu } from 'lucide-react'
import { api, type Project } from '@/api'
import { STEPS } from './AppSidebar'
import ThemeToggle from './ThemeToggle'
import FeedbackButton from './FeedbackButton'
import FontSizeControl from './FontSizeControl'
import LanguageToggle from './LanguageToggle'
import HelpMenu from './HelpMenu'
import NotificationBell from './NotificationBell'

const SECTION_LABEL: Record<string, string> = {
  '/': 'Projects',
  '/settings/llm': 'AI keys (app)',
  '/settings/databases': 'Database keys',
  '/tickets': 'Tickets',
}

/** Normalized page header: breadcrumb derived from the route, global actions on
 * the right. Rendered once by the shell for every authenticated page. */
export default function AppHeader({ onMenuClick }: { onMenuClick?: () => void }) {
  const { t } = useTranslation()
  const location = useLocation()
  const match = location.pathname.match(/^\/projects\/(\d+)/)
  const projectId = match ? Number(match[1]) : null
  const currentSeg = location.pathname.split('/')[3]

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => api.get('/api/projects'),
    enabled: projectId !== null,
  })
  const project = projects.find((p) => p.id === projectId)
  const stepLabel = STEPS.find((s) => s.path === currentSeg)?.label
  // the window title names the page and the project (WCAG 2.4.2)
  const pageTitle = projectId
    ? `${stepLabel ? t(stepLabel) : t(currentSeg === 'settings' ? 'Settings'
        : currentSeg === 'worktime' ? 'Work time' : 'Project')} · ${project?.name ?? t('Project')}`
    : t(location.pathname.startsWith('/help') ? 'Help'
        : SECTION_LABEL[location.pathname] ?? 'LitUbik')
  useEffect(() => {
    document.title = pageTitle === 'LitUbik' ? 'LitUbik' : `${pageTitle} · LitUbik`
  }, [pageTitle])

  const crumbs: React.ReactNode[] = projectId
    ? [
        <Link key="p" to="/" className="transition-colors hover:text-foreground">
          {project?.name ?? t('Project')}
        </Link>,
        <span key="s" className="font-medium text-foreground">
          {stepLabel ? t(stepLabel) : t(currentSeg === 'settings' ? 'Settings' : currentSeg === 'worktime' ? 'Work time' : 'Project')}
        </span>,
      ]
    : [<span key="sec" className="font-medium text-foreground">
        {t(location.pathname.startsWith('/help')
          ? 'Help'
          : SECTION_LABEL[location.pathname] ?? 'LitUbik')}
      </span>]

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background/80 px-3 backdrop-blur sm:px-5">
      <button
        onClick={onMenuClick}
        aria-label={t('Open menu')}
        className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:hidden"
      >
        <Menu className="size-5" />
      </button>
      <nav className="flex min-w-0 items-center gap-2 overflow-hidden text-sm text-muted-foreground"
           aria-label={t('Breadcrumb')}>
        {crumbs.map((c, i) => (
          <span key={i} className="flex min-w-0 items-center gap-2 [&>*]:truncate">
            {i > 0 && <span className="shrink-0 text-muted-foreground/50">/</span>}
            {c}
          </span>
        ))}
      </nav>
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <NotificationBell />
        <HelpMenu />
        <FeedbackButton />
        <LanguageToggle />
        <span className="hidden sm:contents"><FontSizeControl /></span>
        <ThemeToggle />
      </div>
    </header>
  )
}
