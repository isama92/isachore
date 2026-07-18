import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { toast } from 'sonner'
import UserCreate from './UserCreate'
import { renderWithProviders } from '../../test/utils'
import { makeServerSettings, makeUser } from '../../test/fixtures'
import type { ServerSettings } from '../../lib/types'

const admin = makeUser({ id: 1, is_admin: true })

type FetchMock = ReturnType<typeof vi.fn>

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

function stubFetch(opts: {
  settings?: ServerSettings
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const settings = opts.settings ?? makeServerSettings()
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/settings')) return jsonBody(settings)
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, String(input))
    return jsonBody(undefined, 204)
  })
  return fetchMock
}

function bodyOf(fetchMock: FetchMock, method: string, urlEnd: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url).split('?')[0].endsWith(urlEnd) && init?.method === method,
  )
  return JSON.parse((call?.[1] as RequestInit).body as string)
}

function renderCreate(fetchMock: FetchMock) {
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(
    <Routes>
      <Route path="/admin/users/new" element={<UserCreate />} />
      <Route path="/admin/users" element={<div>admin-users-list</div>} />
    </Routes>,
    { authValue: { user: admin }, route: '/admin/users/new' },
  )
}

describe('UserCreate', () => {
  it('creates a user with a password when confirmation is off', async () => {
    const fetchMock = stubFetch({
      settings: makeServerSettings({ require_confirmation: false }),
      mutate: () => jsonBody(makeUser({ id: 3 }), 201),
    })
    const toastSpy = vi.spyOn(toast, 'success')
    renderCreate(fetchMock)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('First name'), 'New')
    await user.type(screen.getByLabelText('Last name'), 'Person')
    await user.type(screen.getByLabelText('Email'), 'new@example.com')
    await user.type(screen.getByLabelText('Password'), 'password12345')
    await user.click(screen.getByRole('button', { name: 'Add user' }))

    expect(await screen.findByText('admin-users-list')).toBeInTheDocument()
    expect(bodyOf(fetchMock, 'POST', '/api/v1/users')).toMatchObject({
      email: 'new@example.com',
      first_name: 'New',
      last_name: 'Person',
      is_admin: false,
      password: 'password12345',
    })
    expect(toastSpy).toHaveBeenCalledWith('User created')
  })

  it('hides the password field and omits it when confirmation is on', async () => {
    const fetchMock = stubFetch({
      settings: makeServerSettings({ require_confirmation: true }),
      mutate: () => jsonBody(makeUser({ id: 3, status: 'waiting_confirmation' }), 201),
    })
    renderCreate(fetchMock)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('First name'), 'New')
    await user.type(screen.getByLabelText('Last name'), 'Person')
    await user.type(screen.getByLabelText('Email'), 'new@example.com')
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(
      screen.getByText('The user will get an email to set their password.'),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add user' }))

    expect(await screen.findByText('admin-users-list')).toBeInTheDocument()
    expect(bodyOf(fetchMock, 'POST', '/api/v1/users')).not.toHaveProperty('password')
  })

  it('surfaces a create error and stays on the form', async () => {
    const fetchMock = stubFetch({
      settings: makeServerSettings({ require_confirmation: false }),
      mutate: () => jsonBody({ detail: 'Email already in use' }, 409),
    })
    renderCreate(fetchMock)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('First name'), 'New')
    await user.type(screen.getByLabelText('Last name'), 'Person')
    await user.type(screen.getByLabelText('Email'), 'dup@example.com')
    await user.type(screen.getByLabelText('Password'), 'password12345')
    await user.click(screen.getByRole('button', { name: 'Add user' }))

    expect(await screen.findByText('Email already in use')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('admin-users-list')).not.toBeInTheDocument())
  })
})
