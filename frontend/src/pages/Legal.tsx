// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import { api } from '@/api'
import { Card } from '@/components/ui/card'
import AppFooter from '@/components/AppFooter'

interface LegalPageData { slug: string; lang: string; body_md: string }

/** Legal notice, terms of use, privacy notice: Markdown served by the
 * backend (a template filled with the instance's values, or the superadmin's
 * own text), readable signed in or not. */
function LegalContent() {
  const { t, i18n } = useTranslation()
  const { slug = 'notice' } = useParams<{ slug: string }>()
  const lang = i18n.language === 'fr' ? 'fr' : 'en'
  const { data: page, isLoading, isError } = useQuery<LegalPageData>({
    queryKey: ['legal', lang, slug],
    queryFn: () => api.get(`/api/legal/${lang}/${slug}`),
    retry: false,
  })
  if (isLoading) return <p className="text-muted-foreground">{t('Loading…')}</p>
  if (isError || !page) {
    return <p className="text-sm text-muted-foreground">
      {t('This page is not published on this instance.')}
    </p>
  }
  return (
    <Card className="p-6">
      <div className="prose prose-sm max-w-none text-sm text-foreground
                      [&_h1]:text-xl [&_h1]:font-bold [&_h1]:mb-3
                      [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2
                      [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5
                      [&_p]:my-2 [&_li]:my-1 [&_strong]:font-semibold
                      [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2">
        <ReactMarkdown components={{
          // the pages link each other: stay inside the app for those
          a: ({ href = '', children }) => href.startsWith('/')
            ? <Link to={href}>{children}</Link>
            : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
        }}>
          {page.body_md}
        </ReactMarkdown>
      </div>
    </Card>
  )
}

/** Inside the signed-in layout. */
export default function LegalPage() {
  return <div className="max-w-3xl"><LegalContent /></div>
}

/** Before signing in: a plain page with a way back to the sign-in screen. */
export function PublicLegalPage() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6">
        <Link to="/login" className="mb-4 inline-block text-sm text-primary hover:underline">
          ← {t('Back to sign-in')}
        </Link>
        <LegalContent />
      </main>
      <AppFooter />
    </div>
  )
}
