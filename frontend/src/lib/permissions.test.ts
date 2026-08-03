import { describe, expect, it } from 'vitest'
import { hasRoleIn, hasRoleSomewhere, householdIdsWithRole, roleAtLeast } from './permissions'
import type { Membership } from './types'

// Organiser of "The Flat" (1), helper in "Mum's place" (2): the cross-household case the
// whole permission model exists to get right.
const MIXED: Membership[] = [
  { household_id: 1, role: 'organiser' },
  { household_id: 2, role: 'helper' },
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
      { household_id: 1, role: 'helper' },
      { household_id: 2, role: 'helper' },
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
