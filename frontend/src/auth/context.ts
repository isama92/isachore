import { createContext } from 'react'
import type { Membership, User } from '../lib/types'

// What the password step resolves to: when twoFactorRequired is true the caller
// must collect a code and call verifyTwoFactor; otherwise the user is signed in.
export type LoginResult = { twoFactorRequired: boolean }

export type AuthContextValue = {
  user: User | null
  impersonating: boolean
  // The signed-in user's household roles, from /auth/me (and the login response, which
  // carries the same shape). A sibling field rather than part of `user` for the same reason
  // `impersonating` is: it is not a property of the user account. Read it through
  // `lib/permissions.ts` rather than comparing roles by hand.
  //
  // Advisory only: the API re-checks every role on every request, so a stale copy (someone
  // changed your role mid-session) shows or hides the wrong nav item until the next
  // /auth/me and grants nothing.
  memberships: Membership[]
  loading: boolean
  login: (email: string, password: string, remember: boolean) => Promise<LoginResult>
  // Second login step: submit a TOTP or recovery code to finish signing in.
  verifyTwoFactor: (code: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
