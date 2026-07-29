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
  // Whether TOTP two-factor auth is enrolled and active for the account.
  two_factor_enabled: boolean
}

export type Me = User & { impersonating: boolean }

// Outcome of the password step of login (backend LoginResponse). When
// two_factor_required is true the user must submit a code to /auth/verify-2fa;
// otherwise the login is complete and `user` is populated.
export type LoginResponse = {
  two_factor_required: boolean
  user: User | null
}

// What POST /profile/2fa/setup returns to drive enrolment: the secret (for
// manual entry), the otpauth URI, and a base64 PNG data URI of the QR code.
export type TwoFactorSetup = {
  secret: string
  otpauth_uri: string
  qr: string
}

// The one-time backup codes returned once at enable / regeneration.
export type RecoveryCodes = {
  recovery_codes: string[]
}

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

// Every period except `manual`, which never recurs and so has neither an interval
// nor weekdays. The interval/weekday translation keys only exist for these four.
export type RecurringPeriod = Exclude<RepeatPeriod, 'manual'>

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
  // null for an unscheduled chore, which has no start date: nothing about it is
  // dated, so the form hides the field and the list shows a placeholder.
  start_date: string | null
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  // Completions one assignee holds before the chore hands off (1 = every
  // completion; "take turns" in the form sets a larger value).
  turn_length: number
  // Periods between occurrences (1 = every period). Not applicable to `manual`.
  repeat_interval: number
  // Which weekdays a weekly chore lands on, as Monday-first indexes 0-6 (the
  // backend's date.weekday(), NOT ISO-8601's 1-7, and NOT JS getDay(), which
  // starts at Sunday: index a Monday-first array instead of calling it). null
  // means unpinned, and only `weekly` carries a value.
  weekdays: number[] | null
  created_at: string
  // The household the chore belongs to (fixed at creation). Drives the list's
  // household column/filter and the edit form's read-only household.
  household: { id: number; name: string }
  // The full pool of people the chore rotates between.
  assignees: User[]
  // Who is on the hook right now (the open occurrence's assignee); null when the
  // chore is unassigned/shared. Every live chore has an open occurrence, whatever
  // its period, so this is not a "nothing left to do" signal.
  current_assignee: User | null
  tags: Tag[]
}

// A completed-chore row for the History view: GET /api/v1/completions.
// `title` is the snapshot taken at completion (survives a rename/soft-delete);
// `completed_at` is when it was checked off and `scheduled_for` the occurrence's
// due datetime, so `days_late` (>0 late, <=0 on time/early) is their date diff.
// `completed_by` is null when the completer's account was hard-deleted, and
// `days_late` is null for an unscheduled chore, which had no due date to miss.
export type HistoryEntry = {
  id: number
  title: string
  scheduled_for: string
  completed_at: string
  days_late: number | null
  completed_by: HouseholdMember | null
  household: { id: number; name: string }
}

// Option lists for the History filters: GET /api/v1/completions/filters.
export type HistoryFilterOptions = {
  households: { id: number; name: string }[]
  members: HouseholdMember[]
}

export type DueStatus = 'overdue' | 'today' | 'soon'

// The time window a Statistics request covers. Sent as ?range=; drives which
// completion metrics are windowed (the overdue snapshot is always live).
export type StatsRange = '7d' | '30d' | '90d'

// Aggregated statistics for the Statistics page: GET /api/v1/stats.
// `range` echoes the request; `granularity` ('day' for 7d/30d, 'week' for 90d)
// tells the time-series chart how to label its axis. KPIs: `completed_in_range`
// and `on_time_rate` follow the range; `currently_overdue` and `active_chores`
// are a live snapshot. `on_time_rate` (fraction not late) is null when none of
// the range's completions had a due date. status_breakdown sums to active_chores.
// Unscheduled chores count in completed_in_range, completions_over_time and
// per_person, but have no due date and so are excluded from currently_overdue,
// active_chores, status_breakdown, punctuality and on_time_rate: punctuality
// therefore does NOT sum to completed_in_range.
export type StatsData = {
  range: StatsRange
  granularity: 'day' | 'week'
  kpis: {
    completed_in_range: number
    currently_overdue: number
    on_time_rate: number | null
    active_chores: number
  }
  // One point per bucket; `bucket` is an ISO date (the day, or the week's Monday).
  completions_over_time: { bucket: string; count: number }[]
  status_breakdown: { overdue: number; today: number; soon: number }
  punctuality: { on_time: number; late: number; early: number }
  // Ranked most-completions-first; excludes completions with no known completer.
  per_person: { user_id: number; first_name: string; last_name: string; count: number }[]
}

// A chore due within the Home window (overdue / today / next 7 days), with its
// server-computed due state plus the household it belongs to and its assignees,
// so a row can show whose chore it is (data-minimised member shape, no email).
// days_until_due is negative when overdue, 0 today.
export type DueChore = {
  id: number
  title: string
  repeats: RepeatPeriod
  // The detail behind `repeats`, so a row reads "Every 2 days" or "Weekly (Tue,
  // Fri)" rather than a bare period.
  repeat_interval: number
  weekdays: number[] | null
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

// A chore with no schedule: GET /api/v1/unscheduled. Deliberately carries no due
// state (there is no deadline) and no `repeats` (every item here is unscheduled).
// `days_since_last_completion` is whole UTC days since it was last done, 0 for
// earlier today, or null if it never has been; it drives both the row's label and
// its recency dot.
export type UnscheduledChore = {
  id: number
  title: string
  days_since_last_completion: number | null
  household: { id: number; name: string }
  assignees: HouseholdMember[]
}

export type UnscheduledData = { items: UnscheduledChore[] }

// Prefill payload carried in router state when cloning a chore. Mirrors the
// creation form's fields plus the source household, so ChoreCreate can seed the
// form and default to the source household (see Chores' clone action).
export type ChoreCloneState = {
  household_id: number
  title: string
  description: string
  // '' when the source chore is unscheduled and so has no start date, matching the
  // form's own spelling of "unset" (and keeping router state plain, as below).
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  turn_length: number
  repeat_interval: number
  // Normalised to [] (like `description` above) so router state stays plain. Must be
  // carried, or cloning an "every 2 days" chore silently produces a plain daily one.
  weekdays: number[]
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
