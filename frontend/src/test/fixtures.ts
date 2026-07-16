import type { Me, User } from '../lib/types'

// Synthetic data only (example.com is reserved for documentation, RFC 2606).
export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    email: 'member@example.com',
    name: 'Test Member',
    is_admin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

export function makeMe(overrides: Partial<Me> = {}): Me {
  const { impersonating = false, ...rest } = overrides
  return { ...makeUser(rest), impersonating }
}
