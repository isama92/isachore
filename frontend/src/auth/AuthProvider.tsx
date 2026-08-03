import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { api, setUnauthorizedHandler } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import type { LoginResponse, Me, Membership, User } from '../lib/types'
import { claimTableSettings, clearTableSettings } from '../components/data-table/useServerTable'
import { useTheme } from '../theme/useTheme'
import i18n, { changeLanguage } from '../i18n/i18n'
import { AuthContext } from './context'

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [impersonating, setImpersonating] = useState(false)
  // Household roles, adopted wherever a user is. Every response that carries the signed-in
  // user carries these too (login and verify-2fa included), so there is no path that sets
  // one without the other and leaves the sidebar guessing. The `?? []` where they are read
  // is for version skew rather than for the type: this app installs as a PWA, so a
  // service-worker-cached shell can outlive the API build it was written against, and an
  // absent list should cost the user some nav items rather than a blank screen.
  const [memberships, setMemberships] = useState<Membership[]>([])
  const [loading, setLoading] = useState(true)
  const { setTheme, setAccent } = useTheme()
  // Mirrors `user` for the 401 handler so it can read the live session without
  // being re-created (and re-registered) on every auth change.
  const userRef = useRef<User | null>(null)

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
        // Every place a user is adopted claims the remembered table settings: here,
        // login, verifyTwoFactor, and refresh (which is where impersonation starting
        // and stopping both land). Filters name colleagues and households and the
        // admin tables save search terms, so they must not cross accounts; the claim
        // clears them only when the account actually differs, since a profile save
        // refreshes too. Session ENDS clear outright, in handleExpiry and logout.
        claimTableSettings(me.id)
        setUser(me)
        setImpersonating(me.impersonating)
        setMemberships(me.memberships ?? [])
        syncAppearance(me)
      })
      .catch(() => {
        if (cancelled) return
        setUser(null)
        setImpersonating(false)
        setMemberships([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [syncAppearance])

  // Keep the ref in step with the state. A setState-free effect, so it is exempt
  // from the no-setState-in-effect rule.
  useEffect(() => {
    userRef.current = user
  }, [user])

  // Central reaction to a session that expired mid-use: an API 401 while we
  // still hold a user clears auth state (RequireAuth then redirects to /login,
  // preserving the current page for return after re-login) and shows a toast.
  // Gate on an active session so pre-auth 401s (a failed login, the logged-out
  // /auth/me probe, verify-2fa) stay no-ops. Use the i18n singleton, not a
  // captured `t`, so the message is in the current language; the fixed toast id
  // collapses several simultaneous 401s into one notice.
  const handleExpiry = useCallback(() => {
    if (!userRef.current) return
    setUser(null)
    setImpersonating(false)
    setMemberships([])
    // Same reason as logout: this is a session ending, and on a shared device it is
    // the likeliest way one ends, since it takes no action from the user at all.
    clearTableSettings()
    toast.info(i18n.t('common.sessionExpired'), { id: 'session-expired' })
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(handleExpiry)
    return () => setUnauthorizedHandler(null)
  }, [handleExpiry])

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<Me>(endpoints.auth.me)
      claimTableSettings(me.id)
      setUser(me)
      setImpersonating(me.impersonating)
      setMemberships(me.memberships ?? [])
      syncAppearance(me)
    } catch {
      setUser(null)
      setImpersonating(false)
      setMemberships([])
    }
  }, [syncAppearance])

  const login = useCallback(
    async (email: string, password: string, remember: boolean) => {
      const res = await api.post<LoginResponse>(endpoints.auth.login, { email, password, remember })
      // When 2FA is required the server has NOT minted a session yet; leave the
      // user null and let the caller collect a code for verifyTwoFactor.
      if (res.two_factor_required || !res.user) {
        return { twoFactorRequired: res.two_factor_required }
      }
      claimTableSettings(res.user.id)
      setUser(res.user)
      setImpersonating(false)
      setMemberships(res.user.memberships ?? [])
      syncAppearance(res.user)
      return { twoFactorRequired: false }
    },
    [syncAppearance],
  )

  const verifyTwoFactor = useCallback(
    async (code: string) => {
      const me = await api.post<Me>(endpoints.auth.verifyTwoFactor, { code })
      claimTableSettings(me.id)
      setUser(me)
      setImpersonating(false)
      setMemberships(me.memberships ?? [])
      syncAppearance(me)
    },
    [syncAppearance],
  )

  const logout = useCallback(async () => {
    await api.post(endpoints.auth.logout)
    setUser(null)
    setImpersonating(false)
    setMemberships([])
    // Remembered table filters name colleagues and households, so they must not
    // outlive the session on a shared device. Theme and language deliberately do
    // survive: they are this browser's preferences, not one account's data.
    clearTableSettings()
  }, [])

  const value = useMemo(
    () => ({ user, impersonating, memberships, loading, login, verifyTwoFactor, logout, refresh }),
    [user, impersonating, memberships, loading, login, verifyTwoFactor, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
