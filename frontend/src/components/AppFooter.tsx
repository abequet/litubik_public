// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useInstance } from './DemoBanner'

/** Credits line, shown under every page (signed in or not). Roles follow the
 * CRediT statement of the SoftwareX paper. Below it, the legal pages the
 * instance publishes and the AGPLv3 §13 source offer — before sign-in too. */
export default function AppFooter({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  const { data: instance } = useInstance()
  const labels: Record<string, string> = {
    notice: t('Legal notice'),
    terms: t('Terms of use'),
    privacy: t('Privacy'),
  }
  const link = 'underline-offset-2 hover:text-foreground hover:underline'
  return (
    <footer className={`space-y-1 px-4 py-4 text-center text-xs text-muted-foreground ${className}`}>
      <div className="flex flex-wrap justify-center gap-x-3 gap-y-1">
        <span>
          {t('Design and development:')}{' '}
          <a href="https://pagespro.univ-gustave-eiffel.fr/adolphe-bequet"
             target="_blank" rel="noopener noreferrer" className={link}>
            Adolphe J. Béquet
          </a>
        </span>
        <span aria-hidden>·</span>
        <span>{t('User-interface design:')} Sébastien Laurent</span>
        <span aria-hidden>·</span>
        <span>{t('Validation and second reviewer:')} Baptiste Bouvier</span>
      </div>
      {instance && (
        <nav aria-label={t('Legal information')}
             className="flex flex-wrap justify-center gap-x-3 gap-y-1">
          {(instance.legal ?? []).map((slug) => (
            <Link key={slug} to={`/legal/${slug}`} className={link}>
              {labels[slug] ?? slug}
            </Link>
          ))}
          {instance.source_url && (
            <a href={instance.source_url} target="_blank" rel="noopener noreferrer"
               className={link}>
              {t('Source code')} ({instance.license}) · v{instance.version}
            </a>
          )}
        </nav>
      )}
    </footer>
  )
}
