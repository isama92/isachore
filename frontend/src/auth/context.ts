import { createContext } from 'react'
import type { User } from '../lib/types'

// What the password step resolves to: when twoFactorRequired is true the caller
// must collect a code and call verifyTwoFactor; otherwise the user is signed in.
export type LoginResult = { twoFactorRequired: boolean }

export type AuthContextValue = {
  user: User | null
  impersonating: boolean
  loading: boolean
  login: (email: string, password: string, remember: boolean) => Promise<LoginResult>
  // Second login step: submit a TOTP or recovery code to finish signing in.
  verifyTwoFactor: (code: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
