import { createContext } from 'react'
import type { User } from '../lib/types'

export type AuthContextValue = {
  user: User | null
  impersonating: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
