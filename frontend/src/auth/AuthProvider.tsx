import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import type { Me, User } from '../lib/types'
import { AuthContext } from './context'

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [impersonating, setImpersonating] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api
      .get<Me>('/api/v1/auth/me')
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setImpersonating(me.impersonating)
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
  }, [])

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<Me>('/api/v1/auth/me')
      setUser(me)
      setImpersonating(me.impersonating)
    } catch {
      setUser(null)
      setImpersonating(false)
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setUser(await api.post<User>('/api/v1/auth/login', { email, password }))
    setImpersonating(false)
  }, [])

  const logout = useCallback(async () => {
    await api.post('/api/v1/auth/logout')
    setUser(null)
    setImpersonating(false)
  }, [])

  const value = useMemo(
    () => ({ user, impersonating, loading, login, logout, refresh }),
    [user, impersonating, loading, login, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
