import type { Chore, Household, Me, Tag, User } from '../lib/types'

// Synthetic data only (example.com is reserved for documentation, RFC 2606).
export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    email: 'member@example.com',
    name: 'Test Member',
    is_admin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    avatar_url: null,
    ...overrides,
  }
}

export function makeMe(overrides: Partial<Me> = {}): Me {
  const { impersonating = false, ...rest } = overrides
  return { ...makeUser(rest), impersonating }
}

export function makeTag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: 'deep-clean',
    color: '#0d9488',
    ...overrides,
  }
}

export function makeChore(overrides: Partial<Chore> = {}): Chore {
  return {
    id: 1,
    title: 'Clean the bathroom',
    description: null,
    start_date: '2026-07-16',
    repeats: 'weekly',
    assignment_type: 'manual',
    created_at: '2026-07-01T00:00:00Z',
    assignees: [],
    tags: [],
    ...overrides,
  }
}

export function makeHousehold(overrides: Partial<Household> = {}): Household {
  return {
    id: 1,
    name: 'Test Household',
    created_at: '2026-01-01T00:00:00Z',
    members: [],
    ...overrides,
  }
}
