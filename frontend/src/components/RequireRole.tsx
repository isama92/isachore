import { Navigate, Outlet } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { hasRoleSomewhere } from '../lib/permissions'
import { routes } from '../lib/routes'
import type { HouseholdRole } from '../lib/types'

/**
 * Layout route gating a page on reaching `min` in at least one household.
 *
 * "At least one" because the pages behind it span every household the user belongs to; the
 * endpoints then return only the households that grant the role, so an organiser in one
 * house and a helper in another reaches the chores list and sees the first house's chores
 * alone. That also means this guard cannot decide anything per household. A page acting on
 * one specific household needs its own check only where the API would let it get that far:
 * `ChoreEdit` does one, because `GET /chores/{id}` is open to every role; `TagEdit` needs
 * none, because `GET /tags/{id}` is role-gated and answers 403 by itself.
 *
 * Convenience, not enforcement - the API re-checks every role on every request. Redirects
 * to Home rather than showing a 403 page, matching RequireAdmin: a hidden nav item means
 * the only way to arrive here is a stale link or a typed URL.
 */
export default function RequireRole({ min }: { min: HouseholdRole }) {
  const { memberships } = useAuth()
  return hasRoleSomewhere(memberships, min) ? <Outlet /> : <Navigate to={routes.home} replace />
}
