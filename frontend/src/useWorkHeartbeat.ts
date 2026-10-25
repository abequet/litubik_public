// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect } from 'react'
import { api } from './api'

/** Reviewer work time (roadmap chantier 14): while a work page is mounted,
 * send a heartbeat every 30 s as long as the tab is visible and the person
 * interacted (keyboard, pointer, scroll) in the last minute. The server
 * folds beats into sessions per stage; nothing about the record on screen
 * is sent. The members panel tells every member that this runs, and shows
 * them their own total; the per-reviewer detail is for the project admin. */
export const HEARTBEAT_MS = 30_000
const IDLE_MS = 60_000

export type WorkStage = 'ta' | 'ft' | 'conflicts' | 'dedup' | 'extraction' | 'appraisal'

export function useWorkHeartbeat(projectId: number | null | undefined, stage: WorkStage | null) {
  useEffect(() => {
    if (!projectId || !stage) return
    let lastInteraction = Date.now()
    const mark = () => { lastInteraction = Date.now() }
    const events: (keyof WindowEventMap)[] =
      ['keydown', 'pointerdown', 'pointermove', 'wheel', 'scroll', 'touchstart']
    for (const ev of events) window.addEventListener(ev, mark, { passive: true })

    const beat = () => {
      if (document.visibilityState !== 'visible') return
      if (Date.now() - lastInteraction > IDLE_MS) return
      api.post(`/api/projects/${projectId}/worktime/heartbeat`, { stage })
        .catch(() => { /* offline or logged out: the session just ends */ })
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') { mark(); beat() }
    }
    document.addEventListener('visibilitychange', onVisibility)
    beat()
    const timer = window.setInterval(beat, HEARTBEAT_MS)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      for (const ev of events) window.removeEventListener(ev, mark)
    }
  }, [projectId, stage])
}
