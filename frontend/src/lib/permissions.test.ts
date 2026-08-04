import { describe, expect, it } from 'vitest'
import {
  assignableRoles,
  hasRoleIn,
  hasRoleSomewhere,
  householdIdsWithRole,
  ownedHouseholdIds,
  ownsAnyHousehold,
  roleAtLeast,
} from './permissions'
import type { Membership } from './types'

// Organiser of "The Flat" (1), helper in "Mum's place" (2): the cross-household case the
// whole permission model exists to get right. Neither is owned, which is the point of the
// ownership tests at the bottom - the strongest role is still not ownership.
const MIXED: Membership[] = [
  { household_id: 1, role: 'organiser', owned: false },
  { household_id: 2, role: 'helper', owned: false },
]

// Owner of 2, merely an organiser of 1. The owner is by definition an organiser, so the roles
// here are identical and only `owned` separates them.
const OWNER: Membership[] = [
  { household_id: 1, role: 'organiser', owned: false },
  { household_id: 2, role: 'organiser', owned: true },
]

describe('roleAtLeast', () => {
  it('ranks organiser above deputy above helper', () => {
    expect(roleAtLeast('organiser', 'helper')).toBe(true)
    expect(roleAtLeast('organiser', 'deputy')).toBe(true)
    expect(roleAtLeast('deputy', 'helper')).toBe(true)
    expect(roleAtLeast('helper', 'deputy')).toBe(false)
    expect(roleAtLeast('deputy', 'organiser')).toBe(false)
  })

  it('counts a role as reaching itself', () => {
    expect(roleAtLeast('helper', 'helper')).toBe(true)
    expect(roleAtLeast('organiser', 'organiser')).toBe(true)
  })
})

describe('hasRoleSomewhere', () => {
  it('is true when any one household grants the role', () => {
    // The nav rule: History shows because household 1 grants it, even though 2 does not.
    expect(hasRoleSomewhere(MIXED, 'organiser')).toBe(true)
    expect(hasRoleSomewhere(MIXED, 'deputy')).toBe(true)
  })

  it('is false when no household grants it', () => {
    const helpers: Membership[] = [
      { household_id: 1, role: 'helper', owned: false },
      { household_id: 2, role: 'helper', owned: false },
    ]
    expect(hasRoleSomewhere(helpers, 'deputy')).toBe(false)
    expect(hasRoleSomewhere(helpers, 'helper')).toBe(true)
  })

  it('is false for a member of no household', () => {
    // A normal, reachable state - nothing provisions a household, so this is every fresh
    // account. It is what gives them the minimal sidebar until they create or join one.
    expect(hasRoleSomewhere([], 'helper')).toBe(false)
    expect(hasRoleSomewhere([], 'organiser')).toBe(false)
  })
})

describe('hasRoleIn', () => {
  it('answers per household, not across them', () => {
    expect(hasRoleIn(MIXED, 1, 'organiser')).toBe(true)
    // The same user, the same role asked for, a different household: this is the check the
    // route guards cannot make, and why ChoreEdit repeats it against the chore's household.
    expect(hasRoleIn(MIXED, 2, 'organiser')).toBe(false)
    expect(hasRoleIn(MIXED, 2, 'helper')).toBe(true)
  })

  it('is false for a household the user does not belong to', () => {
    expect(hasRoleIn(MIXED, 99, 'helper')).toBe(false)
  })
})

describe('householdIdsWithRole', () => {
  it('returns only the households reaching the role', () => {
    expect([...householdIdsWithRole(MIXED, 'organiser')]).toEqual([1])
    expect([...householdIdsWithRole(MIXED, 'helper')]).toEqual([1, 2])
  })

  it('is empty for a member of nothing', () => {
    expect(householdIdsWithRole([], 'helper').size).toBe(0)
  })
})

describe('assignableRoles', () => {
  // The frontend mirror of update_household_member's gate. Empty means "render a badge".
  const owner = { viewerUnrestricted: true, viewerRole: 'organiser' } as const
  const organiser = { viewerUnrestricted: false, viewerRole: 'organiser' } as const

  it('gives the owner all three roles on anybody else', () => {
    expect(assignableRoles({ ...owner, targetIsOwner: false, targetRole: 'helper' })).toEqual([
      'organiser',
      'deputy',
      'helper',
    ])
    expect(assignableRoles({ ...owner, targetIsOwner: false, targetRole: 'organiser' })).toEqual([
      'organiser',
      'deputy',
      'helper',
    ])
  })

  it('never offers a control on the owner’s own row', () => {
    // Not even to the owner themselves: their role moves by transferring the household.
    // The owner-viewer line is what pins the `targetIsOwner` guard; the organiser-viewer one
    // below documents the shape rather than pinning anything (that branch returns [] for an
    // organiser target regardless), so do not simplify this down to just the second line.
    expect(assignableRoles({ ...owner, targetIsOwner: true, targetRole: 'organiser' })).toEqual([])
    expect(assignableRoles({ ...organiser, targetIsOwner: true, targetRole: 'organiser' })).toEqual(
      [],
    )
  })

  it('lets an organiser move deputies and helpers, and nothing else', () => {
    expect(assignableRoles({ ...organiser, targetIsOwner: false, targetRole: 'helper' })).toEqual([
      'deputy',
      'helper',
    ])
    expect(assignableRoles({ ...organiser, targetIsOwner: false, targetRole: 'deputy' })).toEqual([
      'deputy',
      'helper',
    ])
    // `organiser` is absent from those lists, which is what stops an organiser growing the set
    // of people who could demote them.
    expect(
      assignableRoles({ ...organiser, targetIsOwner: false, targetRole: 'helper' }),
    ).not.toContain('organiser')
  })

  it('gives an organiser nothing on a peer organiser, themselves included', () => {
    // Same row either way: an organiser looking at any organiser, which is why demoting
    // yourself needs no separate rule.
    expect(
      assignableRoles({ ...organiser, targetIsOwner: false, targetRole: 'organiser' }),
    ).toEqual([])
  })

  it('gives a deputy, a helper and a non-member nothing', () => {
    for (const viewerRole of ['deputy', 'helper', null] as const) {
      expect(
        assignableRoles({
          viewerUnrestricted: false,
          viewerRole,
          targetIsOwner: false,
          targetRole: 'helper',
        }),
      ).toEqual([])
    }
  })
})

describe('ownsAnyHousehold', () => {
  it('is true when a membership is owned', () => {
    expect(ownsAnyHousehold(OWNER)).toBe(true)
  })

  it('is false for an organiser who owns nothing', () => {
    // The whole reason this is not `hasRoleSomewhere(m, 'organiser')`: MIXED holds the
    // strongest role there is and still owns nothing.
    expect(ownsAnyHousehold(MIXED)).toBe(false)
  })

  it('is false for a member of no household', () => {
    expect(ownsAnyHousehold([])).toBe(false)
  })

  it('treats a membership with no ownership flag as not owned', () => {
    // A cached shell talking to an older API. Fail-closed: hide the item rather than offer a
    // page the server will empty.
    const legacy = [{ household_id: 1, role: 'organiser' }] as unknown as Membership[]
    expect(ownsAnyHousehold(legacy)).toBe(false)
  })
})

describe('ownedHouseholdIds', () => {
  it('returns only the owned households', () => {
    expect(ownedHouseholdIds(OWNER)).toEqual(new Set([2]))
  })

  it('is empty when nothing is owned', () => {
    expect(ownedHouseholdIds(MIXED)).toEqual(new Set())
    expect(ownedHouseholdIds([])).toEqual(new Set())
  })
})
