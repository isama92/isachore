import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import AdminHouseholdEdit from './HouseholdEdit'
import { renderWithProviders } from '../../test/utils'
import { makeHousehold, makeHouseholdMember, makeUser } from '../../test/fixtures'
import type { Household, HouseholdMember } from '../../lib/types'

const admin = makeUser({ id: 1, is_admin: true })

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

function stubFetch(opts: {
  household: Household
  members: HouseholdMember[]
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/members')) {
      return jsonBody({ items: opts.members, total: opts.members.length, page: 1, page_size: 10 })
    }
    if (method === 'GET' && /\/api\/v1\/admin\/households\/\d+$/.test(path)) {
      return jsonBody(opts.household)
    }
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

type FetchMock = ReturnType<typeof vi.fn>

function renderEdit(fetchMock: FetchMock) {
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(
    <Routes>
      <Route path="/admin/households/:id/edit" element={<AdminHouseholdEdit />} />
      <Route path="/admin/households" element={<div>admin-households-list</div>} />
    </Routes>,
    { authValue: { user: admin }, route: '/admin/households/5/edit' },
  )
}

describe('AdminHouseholdEdit', () => {
  it('loads the household and its members from the admin endpoints', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'HQ' }),
      members: [makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
    })
    renderEdit(fetchMock)

    expect(await screen.findByDisplayValue('HQ')).toBeInTheDocument()
    expect(await screen.findByText('Jo Ng')).toBeInTheDocument()
    const membersGet = fetchMock.mock.calls.find(([url]) =>
      String(url).includes('/api/v1/admin/households/5/members'),
    )
    expect(membersGet).toBeTruthy()
  })

  it('lets an admin set the household owner', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'HQ', admin_id: 1 }),
      members: [
        makeHouseholdMember({ id: 1, first_name: 'Site', last_name: 'Admin' }),
        makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
      ],
      mutate: () => jsonBody(makeHousehold({ id: 5, name: 'HQ', admin_id: 2 })),
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Jo Ng')
    await user.click(screen.getByRole('combobox', { name: 'Household admin' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))

    const group = within(screen.getByRole('group', { name: 'Household admin' }))
    await user.click(await group.findByRole('button', { name: 'Save' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Transfer' }))

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect(JSON.parse(String(patch![1]?.body))).toEqual({ admin_id: 2 })
    })
  })

  it('patches the name and navigates back', async () => {
    let patched: string | null = null
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Old' }),
      members: [],
      mutate: (method, url) => {
        if (method === 'PATCH') patched = url
        return jsonBody(makeHousehold({ id: 5, name: 'New' }))
      },
    })
    renderEdit(fetchMock)
    const user = userEvent.setup()

    const input = await screen.findByDisplayValue('Old')
    await user.clear(input)
    await user.type(input, 'New')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('admin-households-list')).toBeInTheDocument()
    expect(patched).toContain('/api/v1/admin/households/5')
  })

  it('restores a deleted household in place', async () => {
    let restored: string | null = null
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'HQ', deleted_at: '2026-06-01T00:00:00Z' }),
      members: [],
      mutate: (method, url) => {
        if (method === 'POST') restored = url
        return jsonBody(makeHousehold({ id: 5, name: 'HQ' }))
      },
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Restore' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Restore household' }))

    await waitFor(() => expect(restored).toContain('/api/v1/admin/households/5/restore'))
    // After restoring, the Restore button is gone (household is active again).
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument(),
    )
  })

  it('shows a not-found message when the household is missing', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonBody({ detail: 'Household not found' }, 404),
    )
    renderEdit(fetchMock)

    expect(await screen.findByText('Household not found')).toBeInTheDocument()
  })

  it('removes a member via the admin endpoint', async () => {
    let removed: string | null = null
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'HQ' }),
      members: [makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
      mutate: (method, url) => {
        if (method === 'DELETE') removed = url
        return jsonBody(undefined, 204)
      },
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    const row = (await screen.findByText('Jo Ng')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Remove' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Remove member' }))

    await waitFor(() => expect(removed).toContain('/api/v1/admin/households/5/members/2'))
  })
})
