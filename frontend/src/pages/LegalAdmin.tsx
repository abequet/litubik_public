// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import { api, ApiError, type User } from '../api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

type LegalValues = {
  operator_name: string
  contact_email: string
  host_name: string
  host_address: string
}

interface LegalOverview {
  stored: LegalValues
  effective: LegalValues & Record<string, string>
  published: string[]
  pages: { slug: string; lang: string; custom: boolean }[]
}

interface LegalPageFull {
  slug: string
  lang: string
  body_md: string
  template_md: string
  custom: boolean
}

const SLUGS = ['notice', 'terms', 'privacy'] as const
const LANGS = ['en', 'fr'] as const

/** Superadmin: the legal pages of the instance. The shipped templates are
 * filled with the values below (empty = automatic default); a page can also
 * be rewritten entirely, and reverted to its template. */
export default function LegalAdminPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: me } = useQuery<User | null>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const { data: overview } = useQuery<LegalOverview>({
    queryKey: ['legal-admin'],
    queryFn: () => api.get('/api/admin/legal'),
    enabled: !!me?.is_admin,
  })
  const [values, setValues] = useState<LegalValues>({
    operator_name: '', contact_email: '', host_name: '', host_address: '',
  })
  useEffect(() => { if (overview) setValues(overview.stored) }, [overview])
  const [savedMsg, setSavedMsg] = useState('')
  const saveValues = useMutation({
    mutationFn: () => api.put('/api/admin/legal/settings', values),
    onSuccess: () => {
      setSavedMsg(t('Saved'))
      queryClient.invalidateQueries({ queryKey: ['legal-admin'] })
      queryClient.invalidateQueries({ queryKey: ['legal-page-admin'] })
      queryClient.invalidateQueries({ queryKey: ['legal'] })
    },
    onError: (e) => setSavedMsg(e instanceof ApiError ? e.message : t('Save failed')),
  })

  const [slug, setSlug] = useState<string>('notice')
  const [lang, setLang] = useState<string>('fr')

  if (!me?.is_admin) {
    return <p className="text-sm text-muted-foreground">
      {t('Only an application admin edits the legal pages.')}
    </p>
  }

  const labels: Record<string, string> = {
    notice: t('Legal notice'), terms: t('Terms of use'), privacy: t('Privacy'),
  }
  const fields: { key: keyof LegalValues; label: string }[] = [
    { key: 'operator_name', label: t('Publisher (name)') },
    { key: 'contact_email', label: t('Contact e-mail') },
    { key: 'host_name', label: t('Host') },
    { key: 'host_address', label: t('Host address') },
  ]

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Legal pages')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('The legal notice, terms of use and privacy notice of this instance, readable without signing in from the footer of every page. A demo instance publishes them all; elsewhere, a page is published once you save it. The templates are filled with the values below — an empty field uses the automatic value shown in grey.')}
      </p>

      <Card className="max-w-2xl p-4">
        <form className="grid gap-3"
              onSubmit={(e) => { e.preventDefault(); saveValues.mutate() }}>
          {fields.map(({ key, label }) => (
            <label key={key} className="grid gap-1 text-sm">
              <span className="font-medium text-foreground">{label}</span>
              <Input value={values[key]}
                     placeholder={overview?.effective[key] || t('(to be completed)')}
                     onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
            </label>
          ))}
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" disabled={saveValues.isPending}>{t('Save')}</Button>
            {savedMsg && <span className="text-xs text-muted-foreground">{savedMsg}</span>}
          </div>
        </form>
      </Card>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        {SLUGS.map((s) => (
          <Button key={s} size="sm" variant={s === slug ? 'default' : 'outline'}
                  onClick={() => setSlug(s)}>
            {labels[s]}
          </Button>
        ))}
        <span className="mx-2 text-muted-foreground" aria-hidden>|</span>
        {LANGS.map((l) => (
          <Button key={l} size="sm" variant={l === lang ? 'default' : 'outline'}
                  onClick={() => setLang(l)}>
            {l.toUpperCase()}
          </Button>
        ))}
        {overview && !overview.published.includes(slug) && (
          <Badge>{t('not published yet')}</Badge>
        )}
      </div>
      <PageEditor key={`${slug}-${lang}`} slug={slug} lang={lang} />
    </div>
  )
}

function PageEditor({ slug, lang }: { slug: string; lang: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: page } = useQuery<LegalPageFull>({
    queryKey: ['legal-page-admin', lang, slug],
    queryFn: () => api.get(`/api/admin/legal/${lang}/${slug}`),
  })
  const [text, setText] = useState<string | null>(null)
  const [preview, setPreview] = useState(false)
  const [msg, setMsg] = useState('')
  const body = text ?? page?.body_md ?? ''
  const refresh = (data: LegalPageFull) => {
    queryClient.setQueryData(['legal-page-admin', lang, slug], data)
    queryClient.invalidateQueries({ queryKey: ['legal-admin'] })
    queryClient.invalidateQueries({ queryKey: ['legal'] })
    queryClient.invalidateQueries({ queryKey: ['instance'] })
    setText(null)
  }
  const save = useMutation({
    mutationFn: () => api.put<LegalPageFull>(`/api/admin/legal/${lang}/${slug}`,
                                             { body_md: body }),
    onSuccess: (data) => { refresh(data); setMsg(t('Saved')) },
    onError: (e) => setMsg(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const revert = useMutation({
    mutationFn: () => api.del<LegalPageFull>(`/api/admin/legal/${lang}/${slug}`),
    onSuccess: (data) => { refresh(data); setMsg(t('Back to the template')) },
  })
  if (!page) return <p className="mt-3 text-sm text-muted-foreground">{t('Loading…')}</p>

  return (
    <Card className="mt-3 max-w-3xl p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        {page.custom
          ? <Badge variant="warning">{t('custom text')}</Badge>
          : <Badge variant="success">{t('template, filled automatically')}</Badge>}
        <Button size="sm" variant="ghost" onClick={() => setPreview(!preview)}>
          {preview ? t('Edit') : t('Preview')}
        </Button>
        <Link to={`/legal/${slug}`} className="text-xs text-primary hover:underline">
          {t('Open the published page')}
        </Link>
      </div>
      {preview ? (
        <div className="prose prose-sm max-w-none rounded-md border border-border p-4 text-sm
                        [&_h1]:text-xl [&_h1]:font-bold [&_h2]:mt-4 [&_h2]:font-semibold
                        [&_ul]:list-disc [&_ul]:pl-5 [&_p]:my-2">
          <ReactMarkdown>{body}</ReactMarkdown>
        </div>
      ) : (
        <Textarea value={body} rows={22} className="font-mono text-xs"
                  aria-label={t('Page text (Markdown)')}
                  onChange={(e) => setText(e.target.value)} />
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={save.isPending || !body.trim()}
                onClick={() => save.mutate()}>
          {t('Save this page')}
        </Button>
        {page.custom && (
          <Button size="sm" variant="outline" disabled={revert.isPending}
                  onClick={() => {
                    if (confirm(t('Discard the custom text and go back to the template?')))
                      revert.mutate()
                  }}>
            {t('Back to the template')}
          </Button>
        )}
        {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
      </div>
    </Card>
  )
}
