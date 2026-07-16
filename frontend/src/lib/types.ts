import type { Accent, Flavour } from '../theme/context'
import type { Language } from '../i18n/languages'

export type User = {
  id: number
  email: string
  first_name: string
  last_name: string
  is_admin: boolean
  is_active: boolean
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
