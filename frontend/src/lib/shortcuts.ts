// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useSyncExternalStore } from 'react'

/** WCAG 2.1.4 (character key shortcuts): the single-letter shortcuts of the
 * screening pages (Y/N/M/S/P) can be switched off from the "?" menu, for
 * people using speech input or whose assistive technology sends keystrokes.
 * Stored per browser; Escape / Enter / Backspace are not affected. */
const KEY = 'litubik-shortcuts'
const EVENT = 'litubik-shortcuts-change'

export function shortcutsEnabled(): boolean {
  try { return localStorage.getItem(KEY) !== 'off' } catch { return true }
}

export function setShortcutsEnabled(on: boolean) {
  try { localStorage.setItem(KEY, on ? 'on' : 'off') } catch { /* private mode */ }
  window.dispatchEvent(new Event(EVENT))
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb)
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

export function useShortcutsEnabled(): boolean {
  return useSyncExternalStore(subscribe, shortcutsEnabled, () => true)
}
