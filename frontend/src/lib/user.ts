import type { User } from './types'

type NameParts = Pick<User, 'first_name' | 'last_name'>

// The display name, composed from the two stored fields.
export function fullName(u: NameParts): string {
  return `${u.first_name} ${u.last_name}`.trim()
}

// Avatar fallback: first letter of the first and last name, uppercased.
// Falls back to '?' only if both are somehow blank.
export function initials(u: NameParts): string {
  const first = u.first_name.trim()
  const last = u.last_name.trim()
  const letters = `${first[0] ?? ''}${last[0] ?? ''}`
  return letters ? letters.toUpperCase() : '?'
}
