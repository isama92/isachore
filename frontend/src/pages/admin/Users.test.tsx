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

// The page fetches both /users and /settings on load, then mutates. This stub
// answers those GETs and lets each test supply the mutation response.
function stubFetch(opts: {
  users: User[]
  settings?: ServerSettings
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const settings = opts.settings ?? makeServerSettings()
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && url.endsWith('/api/v1/settings')) return jsonBody(settings)
    if (method === 'GET' && url.endsWith('/api/v1/users')) return jsonBody(opts.users)
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function bodyOf(fetchMock: FetchMock, method: string, urlEnd: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url).endsWith(urlEnd) && init?.method === method,
  )
  return JSON.parse((call?.[1] as RequestInit).body as string)
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
    // me + member are both active.
    expect(screen.getAllByText('Active')).toHaveLength(2)
    expect(screen.getByText('Waiting confirmation')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
  })

  it('shows the user id in a leading column', async () => {
    stubFetch({ users: [me, member] })
    renderWithProviders(<Users />, { authValue: { user: me } })

    expect(await screen.findByRole('columnheader', { name: 'ID' })).toBeInTheDocument()
    const adminRow = screen.getByText('Admin User').closest('tr')!
    expect(within(adminRow).getByText('1')).toBeInTheDocument()
    const memberRow = screen.getByText('Bob Member').closest('tr')!
    expect(within(memberRow).getByText('2')).toBeInTheDocument()
  })

  it('creates a user with a password when confirmation is off', async () => {
    const fetchMock = stubFetch({
      users: [me],
      settings: makeServerSettings({ require_confirmation: false }),
      mutate: () => jsonBody(makeUser({ id: 3 }), 201),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    await user.click(screen.getByRole('button', { name: 'Add user' }))
    await user.type(await screen.findByLabelText('First name'), 'New')
    await user.type(screen.getByLabelText('Last name'), 'Person')
    await user.type(screen.getByLabelText('Email'), 'new@example.com')
    await user.type(screen.getByLabelText('Password'), 'password12345')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(bodyOf(fetchMock, 'POST', '/api/v1/users')).toMatchObject({
      email: 'new@example.com',
      first_name: 'New',
      last_name: 'Person',
      password: 'password12345',
    })
    expect(toastSpy).toHaveBeenCalledWith('User created')
  })

  it('hides the password field and omits it when confirmation is on', async () => {
    const fetchMock = stubFetch({
      users: [me],
      settings: makeServerSettings({ require_confirmation: true }),
      mutate: () => jsonBody(makeUser({ id: 3, status: 'waiting_confirmation' }), 201),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    await user.click(screen.getByRole('button', { name: 'Add user' }))
    await user.type(await screen.findByLabelText('First name'), 'New')
    await user.type(screen.getByLabelText('Last name'), 'Person')
    await user.type(screen.getByLabelText('Email'), 'new@example.com')
    // No password field is rendered.
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(
      screen.getByText('The user will get an email to set their password.'),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(bodyOf(fetchMock, 'POST', '/api/v1/users')).not.toHaveProperty('password')
  })

  it('edits a user status via the select', async () => {
    const fetchMock = stubFetch({
      users: [me, member],
      mutate: () => jsonBody({ ...member, status: 'disabled' }),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getAllByRole('button', { name: 'Edit' })[1])
    await screen.findByRole('dialog', { name: /Edit Bob Member/ })
    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Disabled' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/2',
        expect.objectContaining({ method: 'PATCH' }),
      ),
    )
    expect(bodyOf(fetchMock, 'PATCH', '/api/v1/users/2')).toMatchObject({ status: 'disabled' })
  })

  it('warns when forcing a never-confirmed user active while confirmation is on', async () => {
    const waiting = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      status: 'active',
      confirmed_at: null,
    })
    stubFetch({
      users: [me, waiting],
      settings: makeServerSettings({ require_confirmation: true }),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getAllByRole('button', { name: 'Edit' })[1])
    const dialog = await screen.findByRole('dialog', { name: /Edit Bob Member/ })
    expect(within(dialog).getByText(/hasn't confirmed their email/i)).toBeInTheDocument()
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

  it('protects the current user from self login-as, deactivate, and edits', async () => {
    stubFetch({ users: [me, member] })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    // Only the member row (not self) exposes these actions
    expect(screen.getAllByRole('button', { name: 'Login as' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Deactivate' })).toHaveLength(1)

    // Editing yourself disables the Admin toggle and the Status select
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const dialog = await screen.findByRole('dialog', { name: /Edit Admin User/ })
    expect(within(dialog).getByRole('checkbox', { name: 'Admin' })).toBeDisabled()
    expect(within(dialog).getByRole('combobox', { name: 'Status' })).toHaveAttribute(
      'data-disabled',
    )
  })
})
