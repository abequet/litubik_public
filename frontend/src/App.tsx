// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type User } from './api'
import { maybeStartTour } from './tour'
import Login from './pages/Login'
import Register from './pages/Register'
import Projects from './pages/Projects'
import ProtocolPage from './pages/Protocol'
import EquationsPage from './pages/Equations'
import SearchPage from './pages/Search'
import DedupPage from './pages/Dedup'
import PrismaPage from './pages/Prisma'
import ReportingPage from './pages/Reporting'
import ScreeningPage from './pages/Screening'
import FulltextPage from './pages/Fulltext'
import FulltextScreeningPage from './pages/Fulltextscreening'
import SnowballingPage from './pages/Snowballing'
import ExtractionPage from './pages/Extraction'
import ResultsPage from './pages/Results'
import TagsPage from './pages/Tags'
import NotesPage from './pages/Notes'
import SyncPage from './pages/Sync'
import ProjectSettingsPage from './pages/ProjectSettings'
import WorkTimePage from './pages/WorkTime'
import LlmSettings from './pages/LlmSettings'
import DatabaseSettings from './pages/DatabaseSettings'
import MyAccessPage from './pages/MyAccess'
import MyIntegrationsPage from './pages/MyIntegrations'
import PaperDownloadPage from './pages/PaperDownload'
import UsersAdminPage from './pages/UsersAdmin'
import InstitutionSettings from './pages/InstitutionSettings'
import TicketsPage from './pages/Tickets'
import HelpPage from './pages/Help'
import LegalPage, { PublicLegalPage } from './pages/Legal'
import LegalAdminPage from './pages/LegalAdmin'
import { PdfWindowProvider } from './components/PdfWindow'
import AppSidebar from './components/AppSidebar'
import AppHeader from './components/AppHeader'
import DemoBanner from './components/DemoBanner'
import AppFooter from './components/AppFooter'
import DemoAccessPage from './pages/DemoAccess'
import BackupPage from './pages/Backup'

export function useMe() {
  return useQuery<User | null>({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.get<User>('/api/auth/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
  })
}

function Layout({ user, children }: { user: User; children: React.ReactNode }) {
  const { t } = useTranslation()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const mainRef = useRef<HTMLElement>(null)

  // mobile: close the drawer after any navigation
  useEffect(() => { setSidebarOpen(false) }, [location.pathname])

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      {/* WCAG 2.4.1: first tab stop of every page jumps over the sidebar */}
      <a href="#main"
         onClick={(e) => { e.preventDefault(); mainRef.current?.focus() }}
         className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground focus:shadow-lg">
        {t('Skip to main content')}
      </a>
      <DemoBanner user={user} />
      <div className="flex min-h-0 flex-1">
        <div className="hidden md:flex">
          <AppSidebar user={user} />
        </div>
        {sidebarOpen && (
          <div className="fixed inset-0 z-50 md:hidden">
            <div className="absolute inset-0 bg-black/50" aria-hidden
                 onClick={() => setSidebarOpen(false)} />
            <div className="absolute inset-y-0 left-0 shadow-2xl">
              <AppSidebar user={user} />
            </div>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <AppHeader onMenuClick={() => setSidebarOpen(true)} />
          {/* the scrolling region must be reachable with Tab so keyboard users can
              scroll it (axe scrollable-region-focusable); the lint rule below does
              not know that exception */}
          {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
          <main id="main" ref={mainRef} tabIndex={0}
                className="flex-1 overflow-y-auto outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset">
            <div className="mx-auto w-full max-w-6xl px-4 py-4 sm:px-6 sm:py-6">{children}</div>
            <AppFooter />
          </main>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const { data: user, isLoading } = useMe()

  // M4: guided tour on the first login of an account (per browser)
  useEffect(() => {
    if (user) maybeStartTour(user.id, { guest: user.is_guest })
  }, [user])

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-background text-muted-foreground">
        Loading…
      </div>
    )
  }

  if (!user) {
    return (
      <>
        <DemoBanner />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/legal/:slug" element={<PublicLegalPage />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </>
    )
  }

  // PdfWindowProvider must wrap the Layout (not only the Routes): the
  // sidebar's FulltextLibrary also calls usePdfWindow() (bug B1)
  return (
    <PdfWindowProvider>
      <Layout user={user}>
        <Routes>
          <Route path="/" element={<Projects />} />
          <Route path="/projects/:projectId/protocol" element={<ProtocolPage />} />
          <Route path="/projects/:projectId/equations" element={<EquationsPage />} />
          <Route path="/projects/:projectId/search" element={<SearchPage />} />
          <Route path="/projects/:projectId/dedup" element={<DedupPage />} />
          <Route path="/projects/:projectId/screening" element={<ScreeningPage />} />
          <Route path="/projects/:projectId/fulltext" element={<FulltextPage />} />
          <Route path="/projects/:projectId/ft-screening" element={<FulltextScreeningPage />} />
          <Route path="/projects/:projectId/snowballing" element={<SnowballingPage />} />
          <Route path="/projects/:projectId/extraction" element={<ExtractionPage />} />
          <Route path="/projects/:projectId/results" element={<ResultsPage />} />
          <Route path="/projects/:projectId/tags" element={<TagsPage />} />
          <Route path="/projects/:projectId/notes" element={<NotesPage />} />
          <Route path="/projects/:projectId/prisma" element={<PrismaPage />} />
          <Route path="/projects/:projectId/reporting" element={<ReportingPage />} />
          <Route path="/projects/:projectId/sync" element={<SyncPage />} />
          <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
          <Route path="/projects/:projectId/worktime" element={<WorkTimePage />} />
          <Route path="/download-papers" element={<PaperDownloadPage />} />
          <Route path="/settings/institutions" element={<MyAccessPage />} />
          <Route path="/settings/integrations" element={<MyIntegrationsPage />} />
          <Route path="/settings/institutions-app" element={<InstitutionSettings />} />
          <Route path="/settings/users" element={<UsersAdminPage />} />
          <Route path="/settings/llm" element={<LlmSettings />} />
          <Route path="/settings/databases" element={<DatabaseSettings />} />
          <Route path="/settings/demo-access" element={<DemoAccessPage />} />
          <Route path="/settings/legal" element={<LegalAdminPage />} />
          <Route path="/legal/:slug" element={<LegalPage />} />
          <Route path="/settings/backup" element={<BackupPage />} />
          <Route path="/tickets" element={<TicketsPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/help/:slug" element={<HelpPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </PdfWindowProvider>
  )
}
