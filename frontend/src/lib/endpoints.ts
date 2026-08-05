// Single source of truth for the backend API surface the frontend talks to.
// Every path is assembled here so the `/api/v1` prefix (and the shape of each
// route) lives in exactly one place instead of being spelled out at ~60 call
// sites. The `api` wrapper in `./api` is the HTTP layer that consumes these.
//
// Boundary: this module owns PATHS, not query state. Pagination, sort and
// filter params (`?page_size=100&sort_by=...`) stay at the call site, appended
// to the path a builder returns — they are per-request state, not endpoint
// identity.

// Resource ids arrive as numbers from the API (chore.id, member.id, ...) and as
// strings from route params (useParams), so path builders accept either.
type Id = string | number

const V1 = '/api/v1'

export const endpoints = {
  auth: {
    me: `${V1}/auth/me`,
    login: `${V1}/auth/login`,
    verifyTwoFactor: `${V1}/auth/verify-2fa`,
    logout: `${V1}/auth/logout`,
    stopImpersonating: `${V1}/auth/stop-impersonating`,
    // Which ways in to offer. Public, and the only endpoint the login page calls.
    methods: `${V1}/auth/methods`,
    // Not an `api` wrapper call: the browser NAVIGATES here, and the backend answers
    // with a redirect to the provider. That is what keeps the flow clear of the prod
    // CSP, which forbids both fetch (connect-src 'self') and form posts
    // (form-action 'self') to another origin but does not govern navigations. The
    // `?return_to=` goes on at the call site, per the header comment above.
    oidcStart: `${V1}/auth/oidc/start`,
  },

  home: `${V1}/home`,
  // The chores with no schedule, which the due view above deliberately omits.
  unscheduled: `${V1}/unscheduled`,

  profile: {
    root: `${V1}/profile`,
    avatar: `${V1}/profile/avatar`,
    // Two-factor auth management, all POST (setup returns the QR/secret;
    // confirm/recoveryCodes return the one-time codes; disable needs a code).
    twoFactor: {
      setup: `${V1}/profile/2fa/setup`,
      confirm: `${V1}/profile/2fa/confirm`,
      recoveryCodes: `${V1}/profile/2fa/recovery-codes`,
      disable: `${V1}/profile/2fa/disable`,
    },
  },

  chores: {
    root: `${V1}/chores`,
    byId: (id: Id) => `${V1}/chores/${id}`,
    complete: (id: Id) => `${V1}/chores/${id}/complete`,
    skip: (id: Id) => `${V1}/chores/${id}/skip`,
  },

  completions: {
    root: `${V1}/completions`,
    filters: `${V1}/completions/filters`,
    byId: (id: Id) => `${V1}/completions/${id}`,
  },

  // Aggregated statistics for the Statistics page. The filter dropdown options
  // (households + members) are reused from completions.filters, so there is no
  // separate stats/filters path.
  stats: `${V1}/stats`,

  // The household activity log for the Logs page (owner-only, server-paginated). Its filter
  // options come from completions.filters too, narrowed client-side to owned households, so
  // there is no logs/filters path either.
  logs: `${V1}/logs`,

  tags: {
    root: `${V1}/tags`,
    byId: (id: Id) => `${V1}/tags/${id}`,
  },

  households: {
    root: `${V1}/households`,
    byId: (id: Id) => `${V1}/households/${id}`,
    // The member roster reached directly by household id (the chore pickers use
    // this). The shared household components reach the same roster through
    // `householdResource(base).members` instead, because their base may be the
    // admin route.
    members: (id: Id) => `${V1}/households/${id}/members`,
    leave: (id: Id) => `${V1}/households/${id}/leave`,
  },

  invitations: {
    byToken: (token: string) => `${V1}/invitations/${token}`,
    accept: (token: string) => `${V1}/invitations/${token}/accept`,
  },

  confirm: {
    byToken: (token: string) => `${V1}/confirm/${token}`,
  },

  users: {
    root: `${V1}/users`,
    byId: (id: Id) => `${V1}/users/${id}`,
    impersonate: (id: Id) => `${V1}/users/${id}/impersonate`,
    resendConfirmation: (id: Id) => `${V1}/users/${id}/resend-confirmation`,
    resetTwoFactor: (id: Id) => `${V1}/users/${id}/reset-2fa`,
  },

  settings: {
    root: `${V1}/settings`,
    testEmail: `${V1}/settings/test-email`,
  },

  adminHouseholds: {
    root: `${V1}/admin/households`,
    byId: (id: Id) => `${V1}/admin/households/${id}`,
    restore: (id: Id) => `${V1}/admin/households/${id}/restore`,
  },
} as const

// A household exposes the same sub-resources whether it is reached through the
// member route (`households.byId`) or the admin route (`adminHouseholds.byId`).
// The shared members/invitations/owner components are handed whichever base
// applies and build their sub-paths relative to it, so the segments live here
// once rather than being hardcoded in three components.
export function householdResource(base: string) {
  return {
    self: base,
    members: `${base}/members`,
    member: (memberId: Id) => `${base}/members/${memberId}`,
    invitations: `${base}/invitations`,
    invitation: (invitationId: Id) => `${base}/invitations/${invitationId}`,
    revokeInvitation: (invitationId: Id) => `${base}/invitations/${invitationId}/revoke`,
  }
}
