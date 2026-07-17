import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import HouseholdEdit from './HouseholdEdit'
import { renderWithProviders } from '../test/utils'
import { makeHousehold, makeHouseholdMember, makeUser } from '../test/fixtures'
import type { Household, HouseholdMember } from '../lib/types'

const me = makeUser({ id: 1 })

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
  household: Household
  members: HouseholdMember[]
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/members')) {
      return jsonBody({
        items: opts.members,
        total: opts.members.length,
        page: 1,
        page_size: 10,
      })
    }
    if (method === 'GET' && path.endsWith('/invitations')) {
      return jsonBody([])
    }
    if (method === 'GET' && /\/api\/v1\/households\/\d+$/.test(path)) {
      return jsonBody(opts.household)
    }
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderEdit(fetchMock: FetchMock) {
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(
    <Routes>
      <Route path="/households/:id/edit" element={<HouseholdEdit />} />
      <Route path="/households" element={<div>households-list</div>} />
    </Routes>,
    { authValue: { user: me }, route: '/households/5/edit' },
  )
}

describe('HouseholdEdit', () => {
  it('loads the household name and its members', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B' }),
      members: [makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
    })
    renderEdit(fetchMock)

    expect(await screen.findByDisplayValue('Flat 3B')).toBeInTheDocument()
    expect(await screen.findByText('Jo Ng')).toBeInTheDocument()
  })

  it('is read-only for a member who does not own the household', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 99 }),
      members: [makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
    })
    renderEdit(fetchMock)

    expect(await screen.findByText('Jo Ng')).toBeInTheDocument()
    // No editable name field, no Save, and no member-remove controls.
    expect(screen.queryByDisplayValue('Flat 3B')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    // A non-owner can leave.
    expect(screen.getByRole('button', { name: 'Leave household' })).toBeInTheDocument()
  })

  it('lets a non-owner leave the household after confirmation', async () => {
    let left: string | null = null
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 99 }),
      members: [makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
      mutate: (method, url) => {
        if (method === 'POST' && url.includes('/leave')) left = url
        return jsonBody(undefined, 204)
      },
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Leave household' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Leave' }))

    expect(await screen.findByText('households-list')).toBeInTheDocument()
    expect(left).toContain('/api/v1/households/5/leave')
  })

  it('badges the owner row and only lets non-owners be removed', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 1 }),
      members: [
        makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' }), // owner
        makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }), // plain member
      ],
    })
    renderEdit(fetchMock)

    // Scope to the members table ("Alex Kim" also shows as the owner-select value).
    await screen.findByText('Jo Ng')
    const table = screen.getByRole('table')
    const ownerRow = within(table).getByText('Alex Kim').closest('tr')!
    const memberRow = within(table).getByText('Jo Ng').closest('tr')!
    // Owner row: Admin badge, no Remove control.
    expect(within(ownerRow).getByText('Admin')).toBeInTheDocument()
    expect(within(ownerRow).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    // Non-owner row: removable.
    expect(within(memberRow).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
    // The owner never sees a Leave button (they must transfer or delete).
    expect(screen.queryByRole('button', { name: 'Leave household' })).not.toBeInTheDocument()
  })

  it('lets the owner transfer ownership to another member', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 1 }),
      members: [
        makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
      ],
      mutate: () => jsonBody(makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 2 })),
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Jo Ng')
    await user.click(screen.getByRole('combobox', { name: 'Household admin' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))

    // Staging the choice reveals a Save button; Save opens a confirmation dialog.
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

    expect(await screen.findByText('households-list')).toBeInTheDocument()
    expect(patched).toContain('/api/v1/households/5')
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(JSON.parse(String(patch![1]?.body))).toEqual({ name: 'New' })
  })

  it('removes a member after confirmation', async () => {
    let removed: string | null = null
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B' }),
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

    await waitFor(() => expect(removed).toContain('/api/v1/households/5/members/2'))
  })

  it('shows the members empty state when the household has none', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B' }),
      members: [],
    })
    renderEdit(fetchMock)

    expect(await screen.findByDisplayValue('Flat 3B')).toBeInTheDocument()
    expect(await screen.findByText('No members yet.')).toBeInTheDocument()
  })

  it('shows a not-found message when the household is missing', async () => {
    const fetchMock = vi.fn(async () => jsonBody({ detail: 'Household not found' }, 404))
    renderEdit(fetchMock)

    expect(await screen.findByText('Household not found')).toBeInTheDocument()
  })
})
