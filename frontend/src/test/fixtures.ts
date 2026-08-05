import type {
  Chore,
  ChoreListRow,
  DueChore,
  HistoryEntry,
  Household,
  HouseholdInvitation,
  HouseholdMember,
  HouseholdMemberWithRole,
  InvitationInfo,
  LogEntry,
  Me,
  ServerSettings,
  StatsData,
  Tag,
  UnscheduledChore,
  User,
} from '../lib/types'

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
    two_factor_enabled: false,
    ...overrides,
  }
}

export function makeServerSettings(overrides: Partial<ServerSettings> = {}): ServerSettings {
  return {
    require_confirmation: false,
    smtp_configured: true,
    smtp_host: 'smtp.example.com',
    smtp_port: 587,
    smtp_from: 'isachore <no-reply@example.com>',
    ...overrides,
  }
}

export function makeMe(overrides: Partial<Me> = {}): Me {
  // Organiser AND owner of household 1, matching makeAuthValue's default and makeHousehold's
  // admin_id, so a /auth/me stub and a directly-supplied auth context describe the same person.
  const {
    impersonating = false,
    memberships = [{ household_id: 1, role: 'organiser' as const, owned: true }],
    ...rest
  } = overrides
  return { ...makeUser(rest), impersonating, memberships }
}

export function makeLogEntry(overrides: Partial<LogEntry> = {}): LogEntry {
  // Household 1, matching makeAuthValue's default and makeHousehold's admin_id, so the default
  // auth context owns the household these rows belong to.
  return {
    id: 1,
    created_at: '2026-07-16T14:30:00Z',
    action: 'chore_created',
    household: { id: 1, name: 'Test Household', timezone: 'UTC' },
    actor: makeHouseholdMember(),
    target: null,
    chore_id: 5,
    chore_title: 'Clean the bathroom',
    changed_fields: [],
    by_admin: false,
    ...overrides,
  }
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
    turn_length: 1,
    repeat_interval: 1,
    weekdays: null,
    created_at: '2026-07-01T00:00:00Z',
    household: { id: 1, name: 'Test Household', timezone: 'UTC' },
    assignees: [],
    current_assignee: null,
    tags: [],
    ...overrides,
  }
}

// A row as GET /api/v1/chores actually sends one: no description, a flag instead. Built off
// makeChore so the shared fields cannot drift, the same way makeMe builds off makeUser.
//
// The description is *deleted* rather than left as null. The list read does not send the
// key at all, and a fixture that carried it would let a component quietly read a value the
// real payload has never had. Widening the local type is what makes delete legal here;
// destructuring it away instead would trip no-unused-vars, which is configured without
// ignoreRestSiblings.
export function makeChoreRow(overrides: Partial<ChoreListRow> = {}): ChoreListRow {
  const { has_description = false, ...rest } = overrides
  const row: Omit<Chore, 'description'> & { description?: string | null } = makeChore(rest)
  delete row.description
  return { ...row, has_description }
}

export function makeHousehold(overrides: Partial<Household> = {}): Household {
  return {
    id: 1,
    name: 'Test Household',
    admin_id: 1,
    // UTC by default, mirroring the backend fixture: every existing date assertion in the
    // suite was written against a UTC day, so any other default would silently re-date them.
    // Timezone-specific cases override it.
    timezone: 'UTC',
    created_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
    member_count: 0,
    chore_count: 0,
    ...overrides,
  }
}

export function makeHouseholdMember(overrides: Partial<HouseholdMember> = {}): HouseholdMember {
  return {
    id: 1,
    first_name: 'Test',
    last_name: 'Member',
    ...overrides,
  }
}

// A member as the household members table receives them. Separate from
// makeHouseholdMember because only the two members endpoints carry a role; assignees,
// History's completed_by and invited_by all use the plain shape.
export function makeHouseholdMemberWithRole(
  overrides: Partial<HouseholdMemberWithRole> = {},
): HouseholdMemberWithRole {
  return {
    ...makeHouseholdMember(overrides),
    role: 'organiser',
    ...overrides,
  }
}

export function makeHouseholdInvitation(
  overrides: Partial<HouseholdInvitation> = {},
): HouseholdInvitation {
  return {
    id: 1,
    url: 'http://localhost:5173/invite?token=tok123',
    status: 'pending',
    created_at: '2026-07-18T00:00:00Z',
    expires_at: '2026-07-19T00:00:00Z',
    ...overrides,
  }
}

export function makeInvitationInfo(overrides: Partial<InvitationInfo> = {}): InvitationInfo {
  return {
    household_name: 'Test Household',
    invited_by: makeHouseholdMember(),
    ...overrides,
  }
}

export function makeHistoryEntry(overrides: Partial<HistoryEntry> = {}): HistoryEntry {
  return {
    id: 1,
    title: 'Clean the bathroom',
    scheduled_for: '2026-07-16T00:00:00Z',
    completed_at: '2026-07-16T14:30:00Z',
    // The zone the closure was judged in. UTC by default like the household fixture, so the
    // existing History date assertions keep meaning what they did.
    completed_timezone: 'UTC',
    skipped: false,
    days_late: 0,
    completed_by: makeHouseholdMember(),
    household: { id: 1, name: 'Test Household', timezone: 'UTC' },
    ...overrides,
  }
}

export function makeStats(overrides: Partial<StatsData> = {}): StatsData {
  return {
    range: '30d',
    granularity: 'day',
    kpis: {
      completed_in_range: 12,
      skipped_in_range: 4,
      currently_overdue: 2,
      on_time_rate: 0.8,
      active_chores: 5,
    },
    completions_over_time: [
      { bucket: '2026-07-01', count: 3, skipped: 1 },
      { bucket: '2026-07-02', count: 5, skipped: 0 },
      { bucket: '2026-07-03', count: 4, skipped: 3 },
    ],
    status_breakdown: { overdue: 2, today: 1, soon: 2 },
    punctuality: { on_time: 8, late: 3, early: 1, skipped: 4 },
    per_person: [
      { user_id: 1, first_name: 'Ava', last_name: 'One', count: 7 },
      { user_id: 2, first_name: 'Ben', last_name: 'Two', count: 5 },
    ],
    ...overrides,
  }
}

export function makeDueChore(overrides: Partial<DueChore> = {}): DueChore {
  return {
    id: 1,
    title: 'Clean the bathroom',
    repeats: 'weekly',
    repeat_interval: 1,
    weekdays: null,
    next_due: '2026-07-20T09:00:00Z',
    days_until_due: 2,
    status: 'soon',
    // Defaults to no instructions, so the marker icon is opt-in per test: most rows are about
    // due state and would otherwise gain an extra button for every query to trip over.
    has_description: false,
    household: { id: 1, name: 'Test Household', timezone: 'UTC' },
    assignees: [],
    ...overrides,
  }
}

// A row of the unscheduled view. Defaults to "done four days ago", i.e. the middle
// (amber) recency bucket, so a test has to opt in to the today/never edges.
export function makeUnscheduledChore(overrides: Partial<UnscheduledChore> = {}): UnscheduledChore {
  return {
    id: 1,
    title: 'Descale the kettle',
    days_since_last_completion: 4,
    // See makeDueChore: opt-in, so the marker icon does not appear on every row by default.
    has_description: false,
    household: { id: 1, name: 'Test Household', timezone: 'UTC' },
    assignees: [],
    ...overrides,
  }
}
