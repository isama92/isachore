import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import AdminHouseholdCreate from './HouseholdCreate'
import { renderWithProviders } from '../../test/utils'
import { makeHousehold, makeUser } from '../../test/fixtures'
import { browserTimezone } from '@/lib/timezones'

const admin = makeUser({ id: 1, is_admin: true })

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

describe('AdminHouseholdCreate', () => {
  it('posts to the admin endpoint and navigates back to the admin list', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonBody(makeHousehold({ id: 9, name: 'HQ' }), 201),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(
      <Routes>
        <Route path="/admin/households/new" element={<AdminHouseholdCreate />} />
        <Route path="/admin/households" element={<div>admin-households-list</div>} />
      </Routes>,
      { authValue: { user: admin }, route: '/admin/households/new' },
    )
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Name'), 'HQ')
    await user.click(screen.getByRole('button', { name: 'Add household' }))

    expect(await screen.findByText('admin-households-list')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(String(post?.[0])).toContain('/api/v1/admin/households')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      name: 'HQ',
      timezone: browserTimezone(),
    })
  })
})
