import { Navigate, Outlet } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { ownsAnyHousehold } from '../lib/permissions'
import { routes } from '../lib/routes'

/**
 * Layout route gating a page on OWNING at least one household.
 *
 * Deliberately its own component rather than a rung on `RequireRole`. Ownership is not on the
 * role ladder: `HOUSEHOLD_ROLES` in lib/types.ts is the frontend's single statement of that
 * ordering and `assignableRoles` derives an organiser's Select options from it, so a
 * pseudo-rung `min="owner"` would put "owner" into a role picker and into a PATCH the API
 * would reject. Widening the prop to `{ min?, owner? }` instead buys one file at the cost of a
 * component with two unrelated modes and two impossible states. So the app now has three
 * guards keyed on three different facts: RequireAdmin (a server-wide flag), RequireRole (a
 * rung, somewhere), RequireOwner (admin_id, somewhere).
 *
 * Takes no prop, like RequireAdmin. "At least one" for RequireRole's reason - the page spans
 * every household and the endpoint returns only the owned ones - so this cannot decide
 * anything per household either. Convenience, not enforcement: the API re-checks.
 */
export default function RequireOwner() {
  const { memberships } = useAuth()
  return ownsAnyHousehold(memberships) ? <Outlet /> : <Navigate to={routes.home} replace />
}
