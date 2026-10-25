// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next'
import { Button } from './ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip'

/** EN/FR switch (M3): persisted in localStorage via i18n.ts. */
export default function LanguageToggle() {
  const { t, i18n } = useTranslation()
  const next = i18n.language === 'fr' ? 'en' : 'fr'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost" size="icon"
          onClick={() => i18n.changeLanguage(next)}
          aria-label={`${i18n.language === 'fr' ? 'FR' : 'EN'} – ${t('Switch language')}`}
          className="text-xs font-semibold tracking-wide"
        >
          {i18n.language === 'fr' ? 'FR' : 'EN'}
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {next === 'fr' ? 'Passer en français' : 'Switch to English'}
      </TooltipContent>
    </Tooltip>
  )
}
