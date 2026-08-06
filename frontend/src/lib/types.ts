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

// What a member may do inside one household, kept in sync with the backend
// HouseholdRole enum. A ladder, not a set of flags: organiser > deputy > helper, and
// `lib/permissions.ts` is the only place that ordering is written down. Household
// *ownership* is a separate fact (`Household.admin_id`) that outranks all three.
export const HOUSEHOLD_ROLES = ['organiser', 'deputy', 'helper'] as const
export type HouseholdRole = (typeof HOUSEHOLD_ROLES)[number]

// One of the signed-in user's household memberships. Carried on `Me` so the sidebar can
// decide what to show before any household has been fetched. `owned` is whether they own
// THIS household - a separate fact from the role rather than a rung on the ladder, and what
// the Logs page is gated on.
export type Membership = { household_id: number; role: HouseholdRole; owned: boolean }

// Whether this server asks new accounts to confirm their address. Server-wide rather than
// personal, and on this payload because it is what tells the Profile page how to read the
// `confirmed_at` beside it: a null means nothing on a server that never asks, and "not
// proved" on one that does.
export type Me = User & {
  impersonating: boolean
  memberships: Membership[]
  email_confirmation_required: boolean
}

// From GET /api/v1/auth/methods, the login page's one request. Public and
// unauthenticated, because the page that asks has nobody signed in yet.
export type AuthMethods = {
  // False only when the server has made the provider the only way in (OIDC_ONLY), which
  // is also exactly when POST /auth/login answers 403.
  password_enabled: boolean
  oidc_enabled: boolean
  // Whatever OIDC_PROVIDER_NAME says, for the "Sign in with ..." label; null when there
  // is no provider, so a client cannot render a button for nothing.
  oidc_provider_name: string | null
}

// Outcome of the password step of login (backend LoginResponse). When
// two_factor_required is true the user must submit a code to /auth/verify-2fa;
// otherwise the login is complete and `user` is populated.
export type LoginResponse = {
  two_factor_required: boolean
  // `Me`, not `User`: the backend returns the memberships with the session it just opened,
  // so the sidebar knows the caller's roles without a follow-up /auth/me. Login sets the
  // auth state directly, which is why this matters - without it the first screen after
  // signing in would render the minimal nav.
  user: Me | null
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
  // Single sign-on, reported the same way SMTP is: a derived "is it usable" boolean plus
  // the non-secret values, read-only from the server's environment. The client secret is
  // never on the wire, exactly as smtp_password is not. Flat oidc_* fields rather than a
  // nested object, to match the smtp_* group above.
  oidc_configured: boolean
  oidc_provider_name: string
  oidc_issuer: string | null
  oidc_client_id: string | null
  // Derived from APP_BASE_URL rather than configured, so it is always present: it is the
  // value an operator registers with the provider, and this page is where they read it.
  oidc_redirect_uri: string
  oidc_only: boolean
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

// The household a chore, closure or log entry belongs to, as embedded in every
// household-scoped payload (the backend's ChoreHouseholdRead). Five payloads carry it, so it
// is named rather than repeated inline.
export type ChoreHousehold = {
  id: number
  name: string
  // The IANA zone this household reckons its days in. On the wire so a timestamp renders in
  // the same zone the server judged it in - otherwise a slot stored at 22:00Z shows as "4 Aug"
  // next to a server-computed "Due today" that means the 5th.
  timezone: string
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
  household: ChoreHousehold
  // The full pool of people the chore rotates between, in the data-minimised member shape
  // (no email): GET /chores/{id} is open to every role, so it must not ship one.
  assignees: HouseholdMember[]
  // Who is on the hook right now (the open occurrence's assignee); null when the
  // chore is unassigned/shared. Every live chore has an open occurrence, whatever
  // its period, so this is not a "nothing left to do" signal.
  current_assignee: HouseholdMember | null
  tags: Tag[]
}

// A row of the chores management list: GET /api/v1/chores. Everything a full Chore has
// except the description, which is answered as a flag - the same treatment DueChore and
// UnscheduledChore already get, and for the same reason: the table renders a marker, and
// at 100 rows a page the HTML was the largest payload in the app. Expressed as an Omit so
// the two cannot drift; anything wanting the description reads GET /chores/{id}.
export type ChoreListRow = Omit<Chore, 'description'> & { has_description: boolean }

// A closed-occurrence row for the History view: GET /api/v1/completions.
// `title` is the snapshot taken at closing (survives a rename/soft-delete);
// `completed_at` is when it was checked off and `scheduled_for` the occurrence's
// due datetime, so `days_late` (>0 late, <=0 on time/early) is their date diff.
// `completed_by` is null when the completer's account was hard-deleted, and
// `days_late` is null for an unscheduled chore, which had no due date to miss.
// `skipped` marks the closures where the work was not done: they belong in the list and
// can be undone like any other, but must read as distinct from real completions. Their
// `days_late` is null too - a real deadline, but no work to have been punctual about.
export type HistoryEntry = {
  id: number
  title: string
  scheduled_for: string
  completed_at: string
  // The zone this closure was judged in. `completed_at` renders in it, not in the household's
  // current zone: `days_late` is computed from it server-side, so rendering the timestamp
  // anywhere else lets a row show a completion date that contradicts its own lateness badge
  // after the household moves. null for closures written before the column existed, where
  // `household.timezone` is the fallback.
  completed_timezone: string | null
  skipped: boolean
  days_late: number | null
  completed_by: HouseholdMember | null
  household: ChoreHousehold
}

// Option lists for the History filters: GET /api/v1/completions/filters. Also reused by
// Statistics and by Logs, each narrowing the household list client-side.
export type HistoryFilterOptions = {
  households: ChoreHousehold[]
  members: HouseholdMember[]
}

// The household log's closed action set, mirroring the backend HouseholdLogAction. Also the
// action filter's options, which is why that filter needs no options call: unlike households
// and members, this list is ours, so no request can teach us a new one.
export const LOG_ACTIONS = [
  'chore_created',
  'chore_updated',
  'chore_deleted',
  'completion_undone',
  'skip_undone',
] as const
export type LogAction = (typeof LOG_ACTIONS)[number]

// The chore fields an update can move, as the API names them (snake_case, stable). Closed so
// the dynamic `logs.fields.*` keys typecheck; a name NOT here degrades to a readable form of
// the raw value rather than to a missing-key string, the same contract FIELD_NAMES has in
// lib/validationError.ts - which is also why `changed_fields` below is string[], not this.
export const LOG_FIELDS = [
  'title',
  'description',
  'start_date',
  'repeats',
  'assignment_type',
  'turn_length',
  'repeat_interval',
  'weekdays',
  'assignees',
  'tags',
] as const
export type LogField = (typeof LOG_FIELDS)[number]

// One row of a household's activity log: GET /api/v1/logs. `chore_title` is the snapshot
// taken when the entry was written, so a renamed or deleted chore still reads; `actor` is null
// when that account was hard-deleted, as History's `completed_by` is; `target` is whose
// closure was undone and is null for the three chore actions. `by_admin` says the action came
// through an impersonated session - a boolean, never the operator's identity.
//
// `action` and `changed_fields` are both deliberately `string`, not `LogAction`/`LogField[]`:
// the wire may name an action or a field this release has never heard of - the API sends them as
// plain strings for exactly that reason - and the renderer degrades instead of the type lying.
// `LOG_ACTIONS` is still the filter's option list, and `isLogAction` is the narrowing guard.
export type LogEntry = {
  id: number
  created_at: string
  action: string
  household: ChoreHousehold
  actor: HouseholdMember | null
  target: HouseholdMember | null
  chore_id: number | null
  chore_title: string | null
  changed_fields: string[]
  by_admin: boolean
}

export type DueStatus = 'overdue' | 'today' | 'soon'

// The time window a Statistics request covers. Sent as ?range=; drives which
// completion metrics are windowed (the overdue snapshot is always live).
export type StatsRange = '7d' | '30d' | '90d'

// Aggregated statistics for the Statistics page: GET /api/v1/stats.
// `range` echoes the request; `granularity` ('day' for 7d/30d, 'week' for 90d)
// tells the time-series chart how to label its axis. KPIs: `completed_in_range`,
// `skipped_in_range` and `on_time_rate` follow the range; `currently_overdue` and
// `active_chores` are a live snapshot. `on_time_rate` (fraction not late) is null when none
// of the range's completions had a due date. status_breakdown sums to active_chores.
// Unscheduled chores count in completed_in_range, completions_over_time and
// per_person, but have no due date and so are excluded from currently_overdue,
// active_chores, status_breakdown, punctuality and on_time_rate: punctuality
// therefore does NOT sum to completed_in_range.
// Skipped occurrences are closures that produced no work, so they are excluded from every
// "work done" figure (completed_in_range, the buckets' `count`, per_person, on_time_rate)
// and reported alongside instead: skipped_in_range, the buckets' `skipped`, and a fourth
// punctuality bucket. Those four DO partition the scheduled occurrences closed in the range
// (skipping an unscheduled chore is refused by the API), but they still do not add up to
// on_time_rate's denominator, which is the first three only.
export type StatsData = {
  range: StatsRange
  granularity: 'day' | 'week'
  kpis: {
    completed_in_range: number
    skipped_in_range: number
    currently_overdue: number
    on_time_rate: number | null
    active_chores: number
  }
  // One point per bucket; `bucket` is an ISO date (the day, or the week's Monday). Two
  // series over the same buckets, both seeded to 0, so the stacked bars line up.
  completions_over_time: { bucket: string; count: number; skipped: number }[]
  status_breakdown: { overdue: number; today: number; soon: number }
  punctuality: { on_time: number; late: number; early: number; skipped: number }
  // Ranked most-completions-first; excludes completions with no known completer, and skips.
  per_person: { user_id: number; first_name: string; last_name: string; count: number }[]
  // Which chores keep being skipped, worst first, capped at five, and only ever chores with
  // at least one skip (never a row reading 0). The one skip figure here that drops
  // soft-deleted chores, since it is a shortlist to act on: their skips are still in
  // skipped_in_range, so this deliberately does not sum to that KPI. `title` is the chore's
  // *current* title, so a rename keeps one row rather than splitting it.
  most_skipped: { chore_id: number; title: string; household_name: string; count: number }[]
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
  // Whether the chore carries written instructions, NOT the instructions themselves. Drives the
  // marker icon on the row; the dialog fetches the chore itself on open, so a household's
  // descriptions never ride along on the landing page's payload.
  has_description: boolean
  household: ChoreHousehold
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
  // See DueChore: a flag, not the description. Not due state, so it does not breach the "no due
  // vocabulary in this view" rule above.
  has_description: boolean
  household: ChoreHousehold
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

// A member as the household members table sees them. Deliberately a separate type rather
// than a `role` field on HouseholdMember: that one is also the type of chore assignees,
// History's `completed_by` and an invitation's `invited_by`, none of which have a
// membership to read a role from (the backend splits HouseholdMemberRead the same way).
export type HouseholdMemberWithRole = HouseholdMember & { role: HouseholdRole }

// A household invite link as the owner or an organiser sees it. `url` is the shareable link;
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

// A household row from the management tables. `admin_id` is the owner (the only member who
// may rename or delete the household, remove members and transfer it; organisers set roles
// and invite). `deleted_at` is null
// for active households; `member_count` counts active members only, `chore_count`
// all chores. The full member list is fetched separately from
// /households/{id}/members.
export type Household = {
  id: number
  name: string
  admin_id: number
  // The IANA zone its chores are due in. Owner-editable; changing it re-dates the
  // household's scheduled chores so they keep their local dates.
  timezone: string
  created_at: string
  deleted_at: string | null
  member_count: number
  chore_count: number
}
