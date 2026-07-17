import type { Chore, Household, Me, ServerSettings, Tag, User } from '../lib/types'

// Synthetic data only (example.com is reserved for documentation, RFC 2606).
export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    email: 'member@example.com',
    first_name: 'Test',
    last_name: 'Member',
    is_admin: false,
    status: 'active',
    confirmed_at: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    avatar_url: null,
    theme: null,
    accent_color: null,
    language: null,
    ...overrides,
  }
}

export function makeServerSettings(overrides: Partial<ServerSettings> = {}): ServerSettings {
  return {
    require_confirmation: false,
    smtp_configured: true,
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
