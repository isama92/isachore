import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import type { Me, User } from '../lib/types'
import { useTheme } from '../theme/useTheme'
import { changeLanguage } from '../i18n/i18n'
import { AuthContext } from './context'

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [impersonating, setImpersonating] = useState(false)
  const [loading, setLoading] = useState(true)
  const { setTheme, setAccent } = useTheme()

  // Adopt the user's saved appearance + language (mirrored into localStorage by
  // setTheme / setAccent / the languageChanged listener). Skip while
  // impersonating so the admin's own preferences are never overwritten by the
  // impersonated user's; a null field means "no choice", so the current default
  // stays.
  const syncAppearance = useCallback(
    (u: Pick<Me, 'theme' | 'accent_color' | 'language'> & { impersonating?: boolean }) => {
      if (u.impersonating) return
      if (u.theme) setTheme(u.theme)
      if (u.accent_color) setAccent(u.accent_color)
      if (u.language) void changeLanguage(u.language)
    },
    [setTheme, setAccent],
  )

  useEffect(() => {
    let cancelled = false
    api
      .get<Me>(endpoints.auth.me)
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setImpersonating(me.impersonating)
        syncAppearance(me)
      })
      .catch(() => {
        if (cancelled) return
        setUser(null)
        setImpersonating(false)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [syncAppearance])

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<Me>(endpoints.auth.me)
      setUser(me)
      setImpersonating(me.impersonating)
      syncAppearance(me)
    } catch {
      setUser(null)
      setImpersonating(false)
    }
  }, [syncAppearance])

  const login = useCallback(
    async (email: string, password: string, remember: boolean) => {
      const me = await api.post<User>(endpoints.auth.login, { email, password, remember })
      setUser(me)
      setImpersonating(false)
      syncAppearance(me)
    },
    [syncAppearance],
  )

  const logout = useCallback(async () => {
    await api.post(endpoints.auth.logout)
    setUser(null)
    setImpersonating(false)
  }, [])

  const value = useMemo(
    () => ({ user, impersonating, loading, login, logout, refresh }),
    [user, impersonating, loading, login, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
