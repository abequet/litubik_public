// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useContext, useEffect, useState } from 'react'

type Theme = 'dark' | 'light'
const STORAGE_KEY = 'litubik-theme'

interface ThemeCtx {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

const ThemeContext = createContext<ThemeCtx | null>(null)

function readInitial(): Theme {
  if (typeof document !== 'undefined' && document.documentElement.classList.contains('dark'))
    return 'dark'
  try {
    return (localStorage.getItem(STORAGE_KEY) as Theme) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

/** Dark-first theme provider. The initial class is set by an inline script in
 * index.html (no FOUC); this keeps React in sync and persists the choice. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readInitial)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* private mode — ignore */
    }
  }, [theme])

  const setTheme = (t: Theme) => setThemeState(t)
  const toggle = () => setThemeState((t) => (t === 'dark' ? 'light' : 'dark'))

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggle }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
