import type { Accent, Flavour } from '../theme/context'
import type { Language } from '../i18n/languages'

// Account lifecycle, kept in sync with the backend UserStatus enum.
export type UserStatus = 'waiting_confirmation' | 'active' | 'disabled'

export type User = {
  id: number
  email: string
  first_name: string
  last_name: string
  is_admin: boolean
  status: UserStatus
  // When the user completed setup; null means they never confirmed (drives the
  // "active but unconfirmed" warning in the admin UI).
  confirmed_at: string | null
  created_at: string
  avatar_url: string | null
  // Appearance preference; null means the client follows its OS-preferred
  // default. The API field is `accent_color`; the theme context calls it `accent`.
  theme: Flavour | null
  accent_color: Accent | null
  // UI language preference; null means the client uses its default (English).
  language: Language | null
}

export type Me = User & { impersonating: boolean }

// Server-wide settings from GET /api/v1/settings (admin-only).
export type ServerSettings = {
  require_confirmation: boolean
  smtp_configured: boolean
}

export type RepeatPeriod = 'manual' | 'hourly' | 'daily' | 'weekly' | 'monthly' | 'yearly'

export type AssignmentType = 'manual' | 'alphabetical' | 'random' | 'least_done'

export type Tag = {
  id: number
  name: string
  color: string
}

export type Chore = {
  id: number
  title: string
  description: string | null
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  created_at: string
  assignees: User[]
  tags: Tag[]
}

// The households endpoint only returns what the assignee picker needs.
export type HouseholdMember = Pick<User, 'id' | 'first_name' | 'last_name'>

export type Household = {
  id: number
  name: string
  created_at: string
  members: HouseholdMember[]
}
