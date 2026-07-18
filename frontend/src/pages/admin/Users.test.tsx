import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { toast } from 'sonner'
import Users from './Users'
import { renderWithProviders } from '../../test/utils'
import { makeServerSettings, makeUser } from '../../test/fixtures'
import type { ServerSettings, User } from '../../lib/types'

const me = makeUser({
  id: 1,
  first_name: 'Admin',
  last_name: 'User',
  email: 'admin@example.com',
  is_admin: true,
})
const member = makeUser({
  id: 2,
  first_name: 'Bob',
  last_name: 'Member',
  email: 'bob@example.com',
})

type FetchMock = ReturnType<typeof vi.fn>

// Minimal Response stand-in for the api wrapper.
function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

// The page fetches a paginated /users envelope plus /settings on load, then
// mutates. This stub answers those GETs (ignoring query params -- the caller
// controls which rows come back) and lets each test supply the mutation
// response. Assertions about which query params were sent inspect the recorded
// request URLs directly.
function stubFetch(opts: {
  users: User[]
  total?: number
  settings?: ServerSettings
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const settings = opts.settings ?? makeServerSettings()
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/settings')) return jsonBody(settings)
    if (method === 'GET' && path.endsWith('/api/v1/users')) {
      return jsonBody({
        items: opts.users,
        total: opts.total ?? opts.users.length,
        page: 1,
        page_size: 20,
      })
    }
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function bodyOf(fetchMock: FetchMock, method: string, urlEnd: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url).split('?')[0].endsWith(urlEnd) && init?.method === method,
  )
  return JSON.parse((call?.[1] as RequestInit).body as string)
}

// The URL of the most recent GET /api/v1/users request (with its query string).
function lastUsersGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(
    ([url, init]) =>
      (init?.method ?? 'GET').toUpperCase() === 'GET' &&
      String(url).split('?')[0].endsWith('/api/v1/users'),
  )
  return String(calls.at(-1)?.[0] ?? '')
}

describe('Users', () => {
  it('renders a row per user with role, status and a "you" badge', async () => {
    const waiting = makeUser({
      id: 3,
      first_name: 'Wanda',
      last_name: 'Waiting',
      email: 'wanda@example.com',
      status: 'waiting_confirmation',
      confirmed_at: null,
    })
    const disabled = makeUser({
      id: 4,
      first_name: 'Dan',
      last_name: 'Disabled',
      email: 'dan@example.com',
      status: 'disabled',
    })
    stubFetch({ users: [me, member, waiting, disabled] })
    renderWithProviders(<Users />, { authValue: { user: me } })

    expect(await screen.findByText('Admin User')).toBeInTheDocument()
    expect(screen.getByText('you')).toBeInTheDocument()
    // Status badges, scoped to each row (the toolbar filter also shows "Active").
    const rowOf = (name: string) => screen.getByText(name).closest('tr')!
    expect(within(rowOf('Admin User')).getByText('Active')).toBeInTheDocument()
    expect(within(rowOf('Bob Member')).getByText('Active')).toBeInTheDocument()
    expect(within(rowOf('Wanda Waiting')).getByText('Waiting confirmation')).toBeInTheDocument()
    expect(within(rowOf('Dan Disabled')).getByText('Disabled')).toBeInTheDocument()
    // Role badge
    expect(within(rowOf('Admin User')).getByText('Admin')).toBeInTheDocument()
    expect(within(rowOf('Bob Member')).getByText('Member')).toBeInTheDocument()
  })

  it('shows the user id and a formatted created date column', async () => {
    const dated = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      created_at: '2026-06-15T12:00:00Z',
    })
    stubFetch({ users: [me, dated] })
    renderWithProviders(<Users />, { authValue: { user: me } })

    expect(await screen.findByRole('columnheader', { name: 'ID' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Created' })).toBeInTheDocument()
    const memberRow = screen.getByText('Bob Member').closest('tr')!
    expect(within(memberRow).getByText('2')).toBeInTheDocument()
    expect(within(memberRow).getByText(/2026/)).toBeInTheDocument()
  })

  it('loads only active users by default, newest first', async () => {
    const fetchMock = stubFetch({ users: [me] })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    const url = lastUsersGet(fetchMock)
    expect(url).toContain('status=active')
    expect(url).toContain('sort_by=created_at')
    expect(url).toContain('sort_dir=desc')
  })

  it('filters by status, and "All statuses" clears the status param', async () => {
    const fetchMock = stubFetch({ users: [me] })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Disabled' }))
    await waitFor(() => expect(lastUsersGet(fetchMock)).toContain('status=disabled'))

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'All statuses' }))
    await waitFor(() => expect(lastUsersGet(fetchMock)).not.toContain('status='))
  })

  it('filters by role', async () => {
    const fetchMock = stubFetch({ users: [me] })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    await user.click(screen.getByRole('combobox', { name: 'Role' }))
    await user.click(await screen.findByRole('option', { name: 'Admin' }))
    await waitFor(() => expect(lastUsersGet(fetchMock)).toContain('role=admins'))
  })

  it('filters by name and email (debounced)', async () => {
    const fetchMock = stubFetch({ users: [me] })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    await user.type(screen.getByLabelText('Filter by name'), 'ali')
    await waitFor(() => expect(lastUsersGet(fetchMock)).toContain('name=ali'), { timeout: 2000 })

    await user.type(screen.getByLabelText('Filter by email'), 'bob')
    await waitFor(() => expect(lastUsersGet(fetchMock)).toContain('email=bob'), { timeout: 2000 })
  })

  it('sorts by the created column', async () => {
    const fetchMock = stubFetch({ users: [me, member] })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    // Default is created_at desc; clicking toggles to asc.
    await user.click(screen.getByRole('button', { name: 'Created' }))
    await waitFor(() => {
      const url = lastUsersGet(fetchMock)
      expect(url).toContain('sort_by=created_at')
      expect(url).toContain('sort_dir=asc')
    })

    // Name is sortable too (a different, unsorted column -> ascending).
    await user.click(screen.getByRole('button', { name: 'Name' }))
    await waitFor(() => {
      const url = lastUsersGet(fetchMock)
      expect(url).toContain('sort_by=name')
      expect(url).toContain('sort_dir=asc')
    })
  })

  it('pages forward when there is more than one page', async () => {
    const fetchMock = stubFetch({ users: [me, member], total: 50 })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => expect(lastUsersGet(fetchMock)).toContain('page=2'))
  })

  it('links to the create and edit pages', async () => {
    stubFetch({ users: [me, member] })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    expect(screen.getByRole('link', { name: 'Add user' })).toHaveAttribute(
      'href',
      '/admin/users/new',
    )
    const memberRow = screen.getByText('Bob Member').closest('tr')!
    expect(within(memberRow).getByRole('link', { name: 'Edit' })).toHaveAttribute(
      'href',
      '/admin/users/2/edit',
    )
  })

  it('resends a confirmation for a waiting user', async () => {
    const waiting = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      status: 'waiting_confirmation',
      confirmed_at: null,
    })
    const fetchMock = stubFetch({
      users: [me, waiting],
      settings: makeServerSettings({ require_confirmation: true }),
      mutate: () => jsonBody(undefined, 204),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getByRole('button', { name: 'Resend confirmation' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/2/resend-confirmation',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(toastSpy).toHaveBeenCalledWith('Confirmation email sent to Bob Member')
  })

  it('hides the resend action when SMTP is not configured', async () => {
    const waiting = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      status: 'waiting_confirmation',
      confirmed_at: null,
    })
    stubFetch({
      users: [me, waiting],
      settings: makeServerSettings({ require_confirmation: true, smtp_configured: false }),
    })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    expect(screen.queryByRole('button', { name: 'Resend confirmation' })).not.toBeInTheDocument()
  })

  it('impersonates a user, refreshes, and navigates home', async () => {
    const fetchMock = stubFetch({
      users: [me, member],
      mutate: () => jsonBody(member),
    })
    const tree = (
      <Routes>
        <Route path="/admin/users" element={<Users />} />
        <Route path="/" element={<div>home-marker</div>} />
      </Routes>
    )
    const { value } = renderWithProviders(tree, {
      route: '/admin/users',
      authValue: { user: me },
    })
    await screen.findByText('Bob Member')

    await userEvent.click(screen.getByRole('button', { name: 'Login as' }))

    await waitFor(() => expect(screen.getByText('home-marker')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/users/2/impersonate',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(value.refresh).toHaveBeenCalled()
  })

  it('deactivates only after confirming in the dialog', async () => {
    const fetchMock = stubFetch({
      users: [me, member],
      mutate: () => jsonBody(undefined, 204),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    // Cancelled -> no request
    await user.click(screen.getByRole('button', { name: 'Deactivate' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }),
    )
    expect(fetchMock.mock.calls.filter(([, i]) => i?.method === 'DELETE')).toHaveLength(0)

    // Confirmed -> DELETE
    await user.click(screen.getByRole('button', { name: 'Deactivate' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Deactivate user',
      }),
    )
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/2',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    )
    expect(toastSpy).toHaveBeenCalledWith('User deactivated')
  })

  it('reactivates a confirmed user to active', async () => {
    const disabled = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      status: 'disabled',
      confirmed_at: '2026-01-01T00:00:00Z',
    })
    const fetchMock = stubFetch({
      users: [me, disabled],
      mutate: () => jsonBody({ ...disabled, status: 'active' }),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getByRole('button', { name: 'Reactivate' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Reactivate user',
      }),
    )
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/2',
        expect.objectContaining({ method: 'PATCH' }),
      ),
    )
    expect(bodyOf(fetchMock, 'PATCH', '/api/v1/users/2')).toMatchObject({ status: 'active' })
  })

  it('reactivates a never-confirmed user back to waiting_confirmation', async () => {
    const disabled = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      status: 'disabled',
      confirmed_at: null,
    })
    const fetchMock = stubFetch({
      users: [me, disabled],
      mutate: () => jsonBody({ ...disabled, status: 'waiting_confirmation' }),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getByRole('button', { name: 'Reactivate' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Reactivate user',
      }),
    )
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/2',
        expect.objectContaining({ method: 'PATCH' }),
      ),
    )
    expect(bodyOf(fetchMock, 'PATCH', '/api/v1/users/2')).toMatchObject({
      status: 'waiting_confirmation',
    })
  })

  it('hides the self-only actions (login-as, deactivate) for the current user', async () => {
    stubFetch({ users: [me, member] })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    // Only the member row (not self) exposes these actions.
    expect(screen.getAllByRole('button', { name: 'Login as' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Deactivate' })).toHaveLength(1)
    // Edit is available on every row (self-edit is allowed; the edit page guards
    // the admin/status fields).
    expect(screen.getAllByRole('link', { name: 'Edit' })).toHaveLength(2)
  })
})
