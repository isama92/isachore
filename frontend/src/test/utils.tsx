import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AuthContext } from '../auth/context'
import ThemeProvider from '../theme/ThemeProvider'
import type { ReactElement } from 'react'
import type { AuthContextValue } from '../auth/context'

export function makeAuthValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    user: null,
    impersonating: false,
    loading: false,
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    refresh: vi.fn(async () => {}),
    ...overrides,
  }
}

type RenderOptions = {
  route?: string
  state?: unknown
  authValue?: Partial<AuthContextValue>
}

export function renderWithProviders(ui: ReactElement, options: RenderOptions = {}) {
  const { route = '/', state, authValue } = options
  const value = makeAuthValue(authValue)
  const entry = state === undefined ? route : { pathname: route, state }
  const result = render(
    <ThemeProvider>
      <AuthContext.Provider value={value}>
        <MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>
      </AuthContext.Provider>
    </ThemeProvider>,
  )
  return { value, ...result }
}

// --- fetch mocking (the api wrapper calls a bare global fetch) --------------

export function jsonResponse(status: number, data: unknown): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

type Route = {
  path: string | RegExp
  method?: string
  status?: number
  // A plain JSON body, or a factory called once per matching request so a test
  // can return a different body on successive calls (e.g. a load then a refetch).
  body?: unknown | (() => unknown)
}

export function mockFetch(routes: Route[]) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const method = (init?.method ?? 'GET').toUpperCase()
    const route = routes.find(
      (r) =>
        (typeof r.path === 'string' ? r.path === url : r.path.test(url)) &&
        (r.method ?? 'GET').toUpperCase() === method,
    )
    if (!route) return jsonResponse(404, { detail: `no mock for ${method} ${url}` })
    const body = typeof route.body === 'function' ? (route.body as () => unknown)() : route.body
    return jsonResponse(route.status ?? 200, body)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
