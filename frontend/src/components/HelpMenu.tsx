// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CircleHelp, Compass, Keyboard, LifeBuoy } from 'lucide-react'
import { startTour } from '@/tour'
import { setShortcutsEnabled, useShortcutsEnabled } from '@/lib/shortcuts'
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from './ui/dropdown-menu'

/** Header "?" menu (M4): Help/FAQ pages + replay of the guided tour. */
export default function HelpMenu() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const shortcuts = useShortcutsEnabled()

  const replayTour = () => {
    // the tour's anchors live on the home page — go there first if needed
    if (location.pathname !== '/') {
      navigate('/')
      setTimeout(startTour, 150)
    } else {
      startTour()
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-tour="help"
        className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground outline-none focus-visible:ring-ring/50 focus-visible:ring-[3px]"
        title={t('Help')}
      >
        <CircleHelp className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem asChild>
          <Link to="/help">
            <LifeBuoy className="size-4" /> {t('Help & FAQ')}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={replayTour}>
          <Compass className="size-4" /> {t('Replay the guided tour')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {/* WCAG 2.1.4: single-character shortcuts must be switchable off */}
        <DropdownMenuCheckboxItem checked={shortcuts}
                                  onCheckedChange={(v) => setShortcutsEnabled(v === true)}
                                  title={t('Single-key shortcuts on the screening pages (Y/N/M/S/P). Turn them off if they conflict with your assistive technology.')}>
          <Keyboard className="size-4" /> {t('Single-key shortcuts')}
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
