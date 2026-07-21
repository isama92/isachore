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

// Envelope returned by the server-side-paginated list endpoints (see
// backend/app/schemas/pagination.py). Drives the reusable DataTable.
export type Page<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

// Server-wide settings from GET /api/v1/settings (admin-only).
export type ServerSettings = {
  require_confirmation: boolean
  smtp_configured: boolean
  smtp_host: string | null
  smtp_port: number
  smtp_from: string | null
}

export type RepeatPeriod = 'manual' | 'daily' | 'weekly' | 'monthly' | 'yearly'

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
  // Completions one assignee holds before the chore hands off (1 = every
  // completion; "take turns" in the form sets a larger value).
  turn_length: number
  created_at: string
  // The household the chore belongs to (fixed at creation). Drives the list's
  // household column/filter and the edit form's read-only household.
  household: { id: number; name: string }
  // The full pool of people the chore rotates between.
  assignees: User[]
  // Who is on the hook right now (the open occurrence's assignee); null when the
  // chore is unassigned/shared or has no open occurrence (a completed one-off).
  current_assignee: User | null
  tags: Tag[]
}

// A completed-chore row for the History view: GET /api/v1/completions.
// `title` is the snapshot taken at completion (survives a rename/soft-delete);
// `completed_at` is when it was checked off and `scheduled_for` the occurrence's
// due datetime, so `days_late` (>0 late, <=0 on time/early) is their date diff.
// `completed_by` is null when the completer's account was hard-deleted.
export type HistoryEntry = {
  id: number
  title: string
  scheduled_for: string
  completed_at: string
  days_late: number
  completed_by: HouseholdMember | null
  household: { id: number; name: string }
}

// Option lists for the History filters: GET /api/v1/completions/filters.
export type HistoryFilterOptions = {
  households: { id: number; name: string }[]
  members: HouseholdMember[]
}

export type DueStatus = 'overdue' | 'today' | 'soon'

// A chore due within the Home window (overdue / today / next 7 days), with its
// server-computed due state plus the household it belongs to and its assignees,
// so a row can show whose chore it is (data-minimised member shape, no email).
// days_until_due is negative when overdue, 0 today.
export type DueChore = {
  id: number
  title: string
  repeats: RepeatPeriod
  next_due: string
  days_until_due: number
  status: DueStatus
  household: { id: number; name: string }
  assignees: HouseholdMember[]
}

// Payload of the Home due view: GET /api/v1/home (progress across the filtered
// scope + the due chores in it).
export type HomeData = {
  progress: { done_today: number; total_today: number }
  items: DueChore[]
}

// Prefill payload carried in router state when cloning a chore. Mirrors the
// creation form's fields plus the source household, so ChoreCreate can seed the
// form and default to the source household (see Chores' clone action).
export type ChoreCloneState = {
  household_id: number
  title: string
  description: string
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  turn_length: number
  assignee_ids: number[]
  tag_ids: number[]
}

// The member list / assignee picker only needs a name (data minimisation).
export type HouseholdMember = Pick<User, 'id' | 'first_name' | 'last_name'>

// A household invite link as the owner sees it. `url` is the shareable link;
// `status` is the stored lifecycle (including `expired`, set by the hourly
// backend sweep) and drives the row's display + action. `expires_at` is kept
// only for the "expires/expired {when}" label.
export type HouseholdInvitation = {
  id: number
  url: string
  status: 'pending' | 'accepted' | 'revoked' | 'expired'
  created_at: string
  expires_at: string
}

// Public info shown on the accept page.
export type InvitationInfo = {
  household_name: string
  invited_by: HouseholdMember
}

// A household row from the management tables. `admin_id` is the owner (the only
// member who may edit the household and manage members). `deleted_at` is null
// for active households; `member_count` counts active members only, `chore_count`
// all chores. The full member list is fetched separately from
// /households/{id}/members.
export type Household = {
  id: number
  name: string
  admin_id: number
  created_at: string
  deleted_at: string | null
  member_count: number
  chore_count: number
}
