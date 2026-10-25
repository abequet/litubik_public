// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import { api } from '@/api'
import { cn } from '@/lib/utils'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { startTour } from '@/tour'

interface HelpTopic { slug: string; title: string }
interface HelpPage extends HelpTopic { content: string }

/** Help/FAQ (M4): markdown topics served by the backend from docs/help/,
 * in the current UI language (French falls back to English per file). */
export default function Help() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const { slug } = useParams<{ slug?: string }>()
  const lang = i18n.language === 'fr' ? 'fr' : 'en'

  const { data: topics = [], isLoading: topicsLoading } = useQuery<HelpTopic[]>({
    queryKey: ['help-topics', lang],
    queryFn: () => api.get(`/api/help/${lang}`),
  })
  const current = slug ?? topics[0]?.slug
  const { data: page, isLoading } = useQuery<HelpPage>({
    queryKey: ['help-page', lang, current],
    queryFn: () => api.get(`/api/help/${lang}/${current}`),
    enabled: !!current,
  })

  return (
    <div className="flex gap-6">
      <nav className="w-56 shrink-0" aria-label={t('Help pages')}>
        <h1 className="mb-3 px-2 text-lg font-semibold tracking-tight">{t('Help')}</h1>
        <ul className="flex flex-col gap-0.5">
          {topics.map((topic) => (
            <li key={topic.slug}>
              <Link
                to={`/help/${topic.slug}`}
                className={cn(
                  'block rounded-md px-2 py-1.5 text-sm transition-colors',
                  topic.slug === current
                    ? 'bg-accent font-medium text-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
              >
                {topic.title}
              </Link>
            </li>
          ))}
        </ul>
        <Button
          variant="outline" size="sm" className="mt-4 w-full"
          onClick={() => { navigate('/'); setTimeout(startTour, 150) }}
        >
          {t('Replay the guided tour')}
        </Button>
      </nav>
      <Card className="min-w-0 flex-1 p-6">
        {!topicsLoading && !current ? (
          <p className="text-muted-foreground">
            {t('Help content is unavailable on this instance.')}
          </p>
        ) : isLoading || !page ? (
          <p className="text-muted-foreground">{t('Loading…')}</p>
        ) : (
          <div className="prose prose-sm max-w-none text-sm text-foreground
                          [&_h1]:text-xl [&_h1]:font-bold [&_h1]:mb-3
                          [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2
                          [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5
                          [&_p]:my-2 [&_li]:my-0.5 [&_strong]:font-semibold
                          [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs">
            <ReactMarkdown>{page.content}</ReactMarkdown>
          </div>
        )}
      </Card>
    </div>
  )
}
