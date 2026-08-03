import { HOUSEHOLD_ROLES, type HouseholdRole, type Membership } from './types'

// Rank per role, derived from the HOUSEHOLD_ROLES tuple (declared strongest first). That
// tuple, in ./types, is where the frontend's ordering actually lives - one place per language,
// the backend's being `_ROLE_LADDER`. To add a role, insert it into the tuple at the right
// position; nothing here needs touching.
const RANK: Record<HouseholdRole, number> = Object.fromEntries(
  HOUSEHOLD_ROLES.map((role, i) => [role, HOUSEHOLD_ROLES.length - 1 - i]),
) as Record<HouseholdRole, number>

/** Whether `role` grants at least everything `min` grants. */
export function roleAtLeast(role: HouseholdRole, min: HouseholdRole): boolean {
  return RANK[role] >= RANK[min]
}

/**
 * Whether the user reaches `min` in at least one household.
 *
 * This is the nav rule. Home, History, Statistics and the chores list all span every
 * household at once, so an item shows when *any* membership grants it and the endpoint
 * then returns only the households that do - an organiser in one house and a helper in
 * another sees Statistics, for the first house only.
 *
 * No memberships means false, which is what gives a brand-new account (a normal, reachable
 * state - nothing provisions a household) the minimal sidebar until they create or join one.
 */
export function hasRoleSomewhere(memberships: Membership[], min: HouseholdRole): boolean {
  return memberships.some((m) => roleAtLeast(m.role, min))
}

/** Whether the user reaches `min` in this specific household. */
export function hasRoleIn(
  memberships: Membership[],
  householdId: number,
  min: HouseholdRole,
): boolean {
  const membership = memberships.find((m) => m.household_id === householdId)
  return membership !== undefined && roleAtLeast(membership.role, min)
}

/**
 * The households where the user reaches `min`, for narrowing a picker or filter list.
 *
 * `hasRoleSomewhere` is what decides whether a page is reachable; this is what stops that
 * page offering a household the caller cannot act in, which would otherwise submit and 403.
 */
export function householdIdsWithRole(memberships: Membership[], min: HouseholdRole): Set<number> {
  return new Set(memberships.filter((m) => roleAtLeast(m.role, min)).map((m) => m.household_id))
}

/**
 * The roles `viewer` may set on `target` in their shared household. Empty means "no control":
 * render the role as a badge.
 *
 * The frontend mirror of `update_household_member`'s gate, kept as one pure function so the
 * members table never spells the rule out itself:
 *
 * - the household owner's own row is never editable, by anybody. They are always an organiser,
 *   and the way to move that is to transfer the household, which promotes the new owner.
 * - the owner may set any of the three on anybody else.
 * - an organiser may only move people between deputy and helper. So they cannot hand out
 *   `organiser`, cannot touch a row that already holds it, and therefore cannot demote
 *   themselves - that last one falls out of the same rule rather than needing its own branch.
 * - a deputy or helper gets nothing.
 *
 * The API re-checks all of this; the point here is to never render a control that would be
 * refused.
 */
export function assignableRoles(opts: {
  viewerIsOwner: boolean
  viewerRole: HouseholdRole | null
  targetIsOwner: boolean
  targetRole: HouseholdRole
}): HouseholdRole[] {
  const { viewerIsOwner, viewerRole, targetIsOwner, targetRole } = opts
  if (targetIsOwner) return []
  if (viewerIsOwner) return [...HOUSEHOLD_ROLES]
  if (viewerRole === 'organiser' && targetRole !== 'organiser') {
    // Derived, not a literal `['deputy', 'helper']`: the backend expresses this as a
    // negation (anything except `organiser`), so a role added to HOUSEHOLD_ROLES has to
    // appear here too or an organiser's Select would silently lack an option the API
    // would have accepted.
    return HOUSEHOLD_ROLES.filter((role) => role !== 'organiser')
  }
  return []
}
