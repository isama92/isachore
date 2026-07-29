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
