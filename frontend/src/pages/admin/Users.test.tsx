import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { toast } from 'sonner'
import Users from './Users'
import { renderWithProviders } from '../../test/utils'
import { makeUser } from '../../test/fixtures'

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

function bodyOf(fetchMock: FetchMock, method: string, urlEnd: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url).endsWith(urlEnd) && init?.method === method,
  )
  return JSON.parse((call?.[1] as RequestInit).body as string)
}

describe('Users', () => {
  it('renders a row per user with role, status and a "you" badge', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonBody([me, member])))
    renderWithProviders(<Users />, { authValue: { user: me } })

    expect(await screen.findByText('Admin User')).toBeInTheDocument()
    expect(screen.getByText('Bob Member')).toBeInTheDocument()
    expect(screen.getByText('Admin')).toBeInTheDocument()
    expect(screen.getByText('Member')).toBeInTheDocument()
    expect(screen.getByText('you')).toBeInTheDocument()
  })

  it('creates a user and reloads the list', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return jsonBody(makeUser({ id: 3 }), 201)
      return jsonBody([me])
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    await user.click(screen.getByRole('button', { name: 'Add user' }))
    await user.type(await screen.findByLabelText('First name'), 'New')
    await user.type(screen.getByLabelText('Last name'), 'Person')
    await user.type(screen.getByLabelText('Email'), 'new@example.com')
    await user.type(screen.getByLabelText('Password'), 'password12345')
    await user.click(screen.getByRole('checkbox', { name: 'Admin' }))
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
      is_admin: true,
    })
    expect(toastSpy).toHaveBeenCalledWith('User created')
  })

  it('omits the password on edit when left blank', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PATCH') return jsonBody(member)
      return jsonBody([me, member])
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getAllByRole('button', { name: 'Edit' })[1])
    await user.click(await screen.findByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/2',
        expect.objectContaining({ method: 'PATCH' }),
      ),
    )
    const body = bodyOf(fetchMock, 'PATCH', '/api/v1/users/2')
    expect(body).not.toHaveProperty('password')
    expect(body).toMatchObject({
      email: 'bob@example.com',
      first_name: 'Bob',
      last_name: 'Member',
    })
  })

  it('includes the password on edit when provided', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PATCH') return jsonBody(member)
      return jsonBody([me, member])
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    await user.click(screen.getAllByRole('button', { name: 'Edit' })[1])
    await user.type(await screen.findByLabelText('Password'), 'brandnew12345')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/2',
        expect.objectContaining({ method: 'PATCH' }),
      ),
    )
    expect(bodyOf(fetchMock, 'PATCH', '/api/v1/users/2')).toMatchObject({
      password: 'brandnew12345',
    })
  })

  it('impersonates a user, refreshes, and navigates home', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return jsonBody(member)
      return jsonBody([me, member])
    })
    vi.stubGlobal('fetch', fetchMock)
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
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') return jsonBody(undefined, 204)
      return jsonBody([me, member])
    })
    vi.stubGlobal('fetch', fetchMock)
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

  it('reactivates only after confirming in the dialog', async () => {
    const inactive = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      is_active: false,
    })
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PATCH') return jsonBody({ ...inactive, is_active: true })
      return jsonBody([me, inactive])
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Bob Member')

    // Cancelled -> no request
    await user.click(screen.getByRole('button', { name: 'Reactivate' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }),
    )
    expect(fetchMock.mock.calls.filter(([, i]) => i?.method === 'PATCH')).toHaveLength(0)

    // Confirmed -> PATCH is_active: true
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
    expect(bodyOf(fetchMock, 'PATCH', '/api/v1/users/2')).toMatchObject({ is_active: true })
    expect(toastSpy).toHaveBeenCalledWith('User reactivated')
  })

  it('protects the current user from self login-as, deactivate, and role edits', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonBody([me, member])))
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Users />, { authValue: { user: me } })
    await screen.findByText('Admin User')

    // Only the member row (not self) exposes these actions
    expect(screen.getAllByRole('button', { name: 'Login as' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Deactivate' })).toHaveLength(1)

    // Editing yourself disables the Admin and Active toggles
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const dialog = await screen.findByRole('dialog', { name: /Edit Admin User/ })
    expect(within(dialog).getByRole('checkbox', { name: 'Admin' })).toBeDisabled()
    expect(within(dialog).getByRole('checkbox', { name: 'Active' })).toBeDisabled()
  })
})

// Minimal Response stand-in for the api wrapper (mirrors test/utils.jsonResponse
// but local so the stateful mocks above can build responses inline).
function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}
