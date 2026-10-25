// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
// Guided onboarding tour (M4, driver.js). Auto-started once per account on
// first login, relaunchable from the header's "?" menu. Steps target
// [data-tour] anchors when present; a missing anchor (e.g. the pipeline
// sidebar while on the home page) degrades to a centered popover.
import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import i18n from './i18n'
import { prefersReducedMotion } from './lib/a11y'

const seenKey = (userId: number) => `litubik-tour-seen-${userId}`

export function startTour(opts: { guest?: boolean } = {}) {
  const t = (s: string) => i18n.t(s)
  // a demo guest session: say first what it is, and that it does not last
  const guestSteps = opts.guest ? [{
    popover: {
      title: t('A demo session'),
      description: t('You are in a guest session of the demo: an example review is already set up for you to explore — screening in progress, conflicts to settle, a PRISMA diagram. Everything is deleted at the daily reset, or at once with "End session and delete my data" in the user menu. The AI features run on a small shared budget, shown in the yellow banner.'),
    },
  }] : []
  driver({
    showProgress: true,
    animate: !prefersReducedMotion(),
    nextBtnText: t('Next'),
    prevBtnText: t('Back'),
    doneBtnText: t('Done'),
    progressText: '{{current}} / {{total}}',
    steps: [
      {
        popover: {
          title: t('Welcome to LitUbik!'),
          description: t('LitUbik guides your systematic literature review from protocol to PRISMA diagram, as a team. This short tour shows you around — you can replay it any time from the ? menu.'),
        },
      },
      ...guestSteps,
      {
        element: '[data-tour="new-project"]',
        popover: {
          title: t('Create a project'),
          description: t('Everything starts here: create a review project, then invite your co-reviewers from the project card (Members). The creator becomes the project admin.'),
        },
      },
      {
        element: '[data-tour="pipeline"]',
        popover: {
          title: t('Follow the pipeline'),
          description: t('Inside a project, the sidebar lists the twelve steps of the review — Protocol, Equations, Search, Dedup, Screening, full text, Snowballing, Extraction, Results, PRISMA, Reporting. Work top to bottom; your current step is highlighted.'),
        },
      },
      {
        element: '[data-tour="settings"]',
        popover: {
          title: t('Project settings'),
          description: t('Project admins configure members, AI keys, AI prompts and screening highlights in the project settings (the ⚙ button on each project card, or Settings in the sidebar).'),
        },
      },
      {
        element: '[data-tour="sync"]',
        popover: {
          title: t('Work as a team'),
          description: t('Colleagues on the same server just join your project. Across separate installations, the Synchronisation page exchanges snapshots and contributions — automatically through a shared folder (Nextcloud, Drive…), or as zip files.'),
        },
      },
      {
        element: '[data-tour="help"]',
        popover: {
          title: t('Need help?'),
          description: t('The ? menu opens the Help/FAQ pages and can replay this tour. Enjoy your review!'),
        },
      },
    ],
  }).drive()
}

/** Start the tour once per account (first login on this browser). */
export function maybeStartTour(userId: number, opts: { guest?: boolean } = {}) {
  try {
    if (localStorage.getItem(seenKey(userId))) return
    localStorage.setItem(seenKey(userId), '1')
  } catch {
    // storage unavailable (private window): show the tour, don't crash
  }
  startTour(opts)
}
