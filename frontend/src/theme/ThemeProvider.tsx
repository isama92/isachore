import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ThemeContext, type Accent, type Flavour } from './context'
import {
  DEFAULT_ACCENT,
  DEFAULT_DARK,
  DEFAULT_LIGHT,
  isAccent,
  isDark,
  isFlavour,
  migrateLegacy,
} from './themes'

const THEME_KEY = 'isachore-theme'
const ACCENT_KEY = 'isachore-accent'

// Read the persisted flavour, migrating the old light/dark toggle values, else
// fall back to the OS preference. Runs in the useState initializer (not an
// effect) so the first render already matches what the pre-hydration script in
// index.html put on <html>. Keep this logic in sync with that script.
function getInitialTheme(): Flavour {
  const stored = localStorage.getItem(THEME_KEY)
  if (isFlavour(stored)) return stored
  const legacy = migrateLegacy(stored)
  if (legacy) return legacy
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? DEFAULT_DARK : DEFAULT_LIGHT
}

function getInitialAccent(): Accent {
  const stored = localStorage.getItem(ACCENT_KEY)
  return isAccent(stored) ? stored : DEFAULT_ACCENT
}

export default function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Flavour>(getInitialTheme)
  const [accent, setAccentState] = useState<Accent>(getInitialAccent)

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    // Keep the .dark class in step with the flavour's group so the `dark:`
    // Tailwind variant and shadcn dark styles still work.
    root.classList.toggle('dark', isDark(theme))
    // public/theme-init.js sets theme-color once before first paint; without
    // this the status bar would keep the old flavour's colour until a reload.
    // Invisible in a browser tab, obvious once installed, where the status bar
    // is the app's own chrome. Read the value back out of the cascade rather
    // than keeping a hex map here: the flavour bases live in index.css, and
    // themes.ts deliberately holds no colours.
    const meta = document.querySelector('meta[name="theme-color"]')
    const background = getComputedStyle(root).getPropertyValue('--background').trim()
    if (meta && background) meta.setAttribute('content', background)
  }, [theme])

  useEffect(() => {
    document.documentElement.dataset.accent = accent
  }, [accent])

  // Persist only on an explicit choice, so a user who never picks a theme keeps
  // following their OS preference on each visit (the mount effects never write).
  const setTheme = useCallback((next: Flavour) => {
    localStorage.setItem(THEME_KEY, next)
    setThemeState(next)
  }, [])
  const setAccent = useCallback((next: Accent) => {
    localStorage.setItem(ACCENT_KEY, next)
    setAccentState(next)
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, setTheme, accent, setAccent }}>
      {children}
    </ThemeContext.Provider>
  )
}
