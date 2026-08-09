// Single source of truth for the client-side (react-router) route paths.
// App.tsx registers the <Route> patterns from here, and every
// navigate() / <Link to> / <Navigate to> / cancelTo reads its target from here,
// so a route and the links pointing at it can never drift.
//
// Parameterised routes expose two shapes, kept adjacent so they stay in
// lockstep: `pattern` (the `:id` form for <Route path>) and `to(id)` (the
// filled form for navigation). Query/hash stays at the call site — routes own
// paths, not query state (e.g. `${routes.invite}?token=...`).

type Id = string | number

export const routes = {
  login: '/login',
  confirm: '/confirm',
  invite: '/invite',

  home: '/',
  unscheduled: '/unscheduled',
  profile: '/profile',
  history: '/history',
  statistics: '/statistics',
  logs: '/logs',

  chores: {
    list: '/chores',
    new: '/chores/new',
    edit: { pattern: '/chores/:id/edit', to: (id: Id) => `/chores/${id}/edit` },
  },

  households: {
    list: '/households',
    new: '/households/new',
    edit: { pattern: '/households/:id/edit', to: (id: Id) => `/households/${id}/edit` },
  },

  tags: {
    list: '/tags',
    new: '/tags/new',
    edit: { pattern: '/tags/:id/edit', to: (id: Id) => `/tags/${id}/edit` },
  },

  admin: {
    users: {
      list: '/admin/users',
      new: '/admin/users/new',
      edit: { pattern: '/admin/users/:id/edit', to: (id: Id) => `/admin/users/${id}/edit` },
    },
    households: {
      list: '/admin/households',
      new: '/admin/households/new',
      edit: {
        pattern: '/admin/households/:id/edit',
        to: (id: Id) => `/admin/households/${id}/edit`,
      },
    },
    serverSettings: '/admin/server-settings',
  },
} as const

// A `next` longer than this is dropped rather than truncated: a truncated path is a
// *different* path, and sending somebody to a silently mangled url is worse than sending
// them home. Matches the backend's cap, which is the width of the column it stores in.
const MAX_RETURN_PATH = 255

// A base that is definitely not a real origin, used only to ask the URL parser "where would
// this resolve to". `.invalid` is reserved by RFC 2606 for exactly this. A constant rather
// than `window.location.origin` so the function stays pure and testable; the question being
// asked - does this stay on the base origin - has the same answer either way.
const SAME_ORIGIN_BASE = 'https://isachore.invalid'

/**
 * A site-relative path we are willing to send a browser to after sign-in, or null.
 *
 * The open-redirect guard for `?next=`, which the prod nginx puts on its redirect when it
 * turns an anonymous reader away from `/docs`. That value is a literal on the nginx side,
 * but the parameter itself is client-controlled - anybody can type
 * `/login?next=https://evil.example` - and the SPA is static, so there is no server in this
 * path to catch it. This function is the only thing between that url and an open redirect on
 * our own login page.
 *
 * Everything that does not resolve to our own origin is DISCARDED rather than corrected,
 * because there is no reading of `https://evil` or `//evil` worth honouring.
 *
 * **The origin check asks the URL parser rather than matching strings, and that is the whole
 * point.** A hand-written list of forbidden shapes (`//`, a backslash, ...) looks complete
 * and is not: the WHATWG parser strips every ASCII tab, LF and CR from a url *before*
 * parsing it, so `/%09/evil.example` arrives here as `/\t/evil.example` - one leading slash,
 * no `//`, no backslash, under the cap - and `location.assign` then sends the browser to
 * `https://evil.example/`. The first version of this function shipped with exactly that
 * hole. Parsing with the same algorithm the sink uses is what makes the answer match what
 * the browser will actually do, and it is why the **normalised** path is returned rather
 * than the caller's string: handing back the raw value would let the sink re-parse it and
 * reach a different conclusion.
 *
 * Related, and NOT the same function: `_safe_return_to` in `backend/app/api/v1/oidc.py`
 * guards the SSO `return_to` with the same *rule*. The rule alone is not what makes either
 * one safe - the sinks differ, and Starlette percent-encodes a `Location` header where
 * `location.assign` does not - so keep them in step, but do not assume one is proved by the
 * other.
 */
export function safeReturnPath(raw: string | null | undefined): string | null {
  // Site-relative only. The parser would happily resolve `docs` against the base too, but a
  // bare path is not what anything here means to send, so it is refused rather than guessed.
  if (!raw || !raw.startsWith('/')) return null
  if (raw.length > MAX_RETURN_PATH) return null
  let resolved: URL
  try {
    resolved = new URL(raw, SAME_ORIGIN_BASE)
  } catch {
    return null
  }
  if (resolved.origin !== SAME_ORIGIN_BASE) return null
  const path = `${resolved.pathname}${resolved.search}${resolved.hash}`
  // Checked again after normalising, because percent-encoding LENGTHENS: `/a b` comes back
  // as `/a%20b`, so an input under the cap can leave over it. The cap exists to match the
  // 255-char column the backend stores this in when it rides on to SSO as `return_to`, and
  // that is the value it stores - so measuring only the input would let a path through here
  // that `_safe_return_to` then silently drops, landing the user on Home.
  return path.length > MAX_RETURN_PATH ? null : path
}
