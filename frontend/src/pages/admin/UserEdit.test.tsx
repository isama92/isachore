import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import UserEdit from './UserEdit'
import { renderWithProviders } from '../../test/utils'
import { makeServerSettings, makeUser } from '../../test/fixtures'
import type { ServerSettings, User } from '../../lib/types'

const admin = makeUser({
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

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

function stubFetch(opts: {
  user: User
  settings?: ServerSettings
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const settings = opts.settings ?? makeServerSettings()
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/settings')) return jsonBody(settings)
    if (method === 'GET' && /\/api\/v1\/users\/\d+$/.test(path)) return jsonBody(opts.user)
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, String(input))
    return jsonBody(undefined, 204)
  })
}

function bodyOf(fetchMock: FetchMock, method: string, urlEnd: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url).split('?')[0].endsWith(urlEnd) && init?.method === method,
  )
  return JSON.parse((call?.[1] as RequestInit).body as string)
}

function renderEdit(fetchMock: FetchMock, opts: { route?: string; user?: User } = {}) {
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(
    <Routes>
      <Route path="/admin/users/:id/edit" element={<UserEdit />} />
      <Route path="/admin/users" element={<div>admin-users-list</div>} />
    </Routes>,
    { authValue: { user: opts.user ?? admin }, route: opts.route ?? '/admin/users/2/edit' },
  )
}

describe('UserEdit', () => {
  it('prefills the form from the loaded user', async () => {
    renderEdit(stubFetch({ user: member }))

    expect(await screen.findByDisplayValue('Bob')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Member')).toBeInTheDocument()
    expect(screen.getByDisplayValue('bob@example.com')).toBeInTheDocument()
  })

  it('edits the status and patches, then navigates back', async () => {
    const fetchMock = stubFetch({
      user: member,
      mutate: () => jsonBody({ ...member, status: 'disabled' }),
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByDisplayValue('Bob')
    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Disabled' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('admin-users-list')).toBeInTheDocument()
    expect(bodyOf(fetchMock, 'PATCH', '/api/v1/users/2')).toMatchObject({ status: 'disabled' })
  })

  it('warns when the loaded user is active but never confirmed and confirmation is on', async () => {
    const waiting = makeUser({
      id: 2,
      first_name: 'Bob',
      last_name: 'Member',
      email: 'bob@example.com',
      status: 'active',
      confirmed_at: null,
    })
    renderEdit(
      stubFetch({ user: waiting, settings: makeServerSettings({ require_confirmation: true }) }),
    )

    expect(await screen.findByText(/hasn't confirmed their email/i)).toBeInTheDocument()
  })

  it('disables the admin and status fields when editing yourself', async () => {
    renderEdit(stubFetch({ user: admin }), { route: '/admin/users/1/edit', user: admin })

    await screen.findByDisplayValue('Admin')
    expect(screen.getByRole('checkbox', { name: 'Admin' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveAttribute('data-disabled')
  })

  it('shows a not-found message when the user is missing', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split('?')[0]
      if (path.endsWith('/api/v1/settings')) return jsonBody(makeServerSettings())
      return jsonBody({ detail: 'User not found' }, 404)
    })
    renderEdit(fetchMock)

    expect(await screen.findByText('User not found')).toBeInTheDocument()
  })
})
