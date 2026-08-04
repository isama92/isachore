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
 * This is the nav rule. Home, Statistics and the chores list all span every household at
 * once, so an item shows when *any* membership grants it and the endpoint then returns only
 * the households that do - an organiser in one house and a helper in another sees
 * Statistics, for the first house only. History is not on that list: it is unconditional,
 * because its endpoint narrows *within* a household (your own closures where you are a
 * helper) instead of dropping it, so there is no rung to gate the item on.
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
 * Whether the user owns at least one household.
 *
 * The nav rule for Logs. Ownership is `households.admin_id`, NOT a rung on the role ladder:
 * the owner is by definition an organiser, but an organiser is not an owner, and only the
 * owner renames or deletes the household, removes members or transfers it. So this is a
 * sibling of `hasRoleSomewhere` rather than a call to it.
 *
 * False for a member of none, and false for a membership that carries no ownership flag at
 * all (an older API answering a cached shell). Both hide the item, which is the fail-closed
 * direction: the alternative is offering a page the API will empty.
 */
export function ownsAnyHousehold(memberships: Membership[]): boolean {
  return memberships.some((m) => m.owned)
}

/**
 * The households the user owns, for narrowing a picker or filter list. The ownership
 * counterpart of `householdIdsWithRole`, needed for the same reason: `/completions/filters` is
 * not narrowed server-side, so Logs would otherwise offer a household its list has no rows for.
 */
export function ownedHouseholdIds(memberships: Membership[]): Set<number> {
  return new Set(memberships.filter((m) => m.owned).map((m) => m.household_id))
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
 * - an unrestricted viewer may set any of the three on anybody else. That is the household
 *   owner, and also a site admin on the Admin > Households surface: the organiser asymmetry
 *   below exists so an organiser cannot grow the set of people who could demote *them*, which
 *   is a statement about a household member and says nothing about an operator.
 * - an organiser may only move people between deputy and helper. So they cannot hand out
 *   `organiser`, cannot touch a row that already holds it, and therefore cannot demote
 *   themselves - that last one falls out of the same rule rather than needing its own branch.
 * - a deputy or helper gets nothing.
 *
 * The API re-checks all of this; the point here is to never render a control that would be
 * refused.
 */
export function assignableRoles(opts: {
  // The household owner, or a site admin on the admin surface. Named for the capability
  // rather than for ownership, because those are two different people with one reach.
  viewerUnrestricted: boolean
  viewerRole: HouseholdRole | null
  targetIsOwner: boolean
  targetRole: HouseholdRole
}): HouseholdRole[] {
  const { viewerUnrestricted, viewerRole, targetIsOwner, targetRole } = opts
  if (targetIsOwner) return []
  if (viewerUnrestricted) return [...HOUSEHOLD_ROLES]
  if (viewerRole === 'organiser' && targetRole !== 'organiser') {
    // Derived, not a literal `['deputy', 'helper']`: the backend expresses this as a
    // negation (anything except `organiser`), so a role added to HOUSEHOLD_ROLES has to
    // appear here too or an organiser's Select would silently lack an option the API
    // would have accepted.
    return HOUSEHOLD_ROLES.filter((role) => role !== 'organiser')
  }
  return []
}
