import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import HouseholdEdit from './HouseholdEdit'
import { renderWithProviders } from '../test/utils'
import { makeHousehold, makeHouseholdMemberWithRole, makeUser } from '../test/fixtures'
import type { Household, HouseholdMemberWithRole } from '../lib/types'

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
  members: HouseholdMemberWithRole[]
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
  return renderWithProviders(
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
      members: [makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
    })
    renderEdit(fetchMock)

    expect(await screen.findByDisplayValue('Flat 3B')).toBeInTheDocument()
    expect(await screen.findByText('Jo Ng')).toBeInTheDocument()
  })

  it('is read-only for a member who does not own the household', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 99 }),
      members: [makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
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
      members: [makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
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
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }), // owner
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' }), // plain member
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

  // --- roles ------------------------------------------------------------
  //
  // The Select gate is `canEditRoles && row is not the owner`. Each test below satisfies
  // one clause and varies the other, so neither can be deleted without a failure: a test
  // that changed both at once would pass on whichever clause survived.

  it('lets the owner set another member’s role', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, admin_id: 1 }),
      members: [
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMemberWithRole({
          id: 2,
          first_name: 'Jo',
          last_name: 'Ng',
          role: 'helper',
        }),
      ],
      mutate: () =>
        jsonBody(
          makeHouseholdMemberWithRole({
            id: 2,
            first_name: 'Jo',
            last_name: 'Ng',
            role: 'deputy',
          }),
        ),
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Jo Ng')
    // The label carries the member's name: one Select per row, so a bare "Role" would be
    // ambiguous the moment a household has two members.
    await user.click(screen.getByRole('combobox', { name: 'Role for Jo Ng' }))
    await user.click(await screen.findByRole('option', { name: 'Deputy' }))

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([url, init]) => init?.method === 'PATCH' && String(url).endsWith('/members/2'),
      )
      expect(patch).toBeTruthy()
      expect(JSON.parse(String(patch![1]?.body))).toEqual({ role: 'deputy' })
    })
  })

  it('shows the owner’s own role as a badge, not a control', async () => {
    // canEditRoles is true here (this is the owner's own view), so the only thing keeping
    // the owner's row read-only is the adminId clause.
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, admin_id: 1 }),
      members: [
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng', role: 'deputy' }),
      ],
    })
    renderEdit(fetchMock)

    await screen.findByText('Jo Ng')
    const table = screen.getByRole('table')
    const ownerRow = within(table).getByText('Alex Kim').closest('tr')!
    expect(within(ownerRow).queryByRole('combobox')).not.toBeInTheDocument()
    expect(within(ownerRow).getByText('Organiser')).toBeInTheDocument()
    // And the other row proves the view is otherwise editable.
    expect(screen.getByRole('combobox', { name: 'Role for Jo Ng' })).toBeInTheDocument()
  })

  it('shows a non-owner every role as a badge', async () => {
    // The mirror of the test above: the row is NOT the owner's, so canEditRoles is the only
    // clause left to keep it read-only.
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, admin_id: 99 }),
      members: [
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng', role: 'helper' }),
      ],
    })
    renderEdit(fetchMock)

    await screen.findByText('Jo Ng')
    expect(screen.queryByRole('combobox', { name: 'Role for Jo Ng' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('Helper')).toBeInTheDocument()
  })

  it('surfaces a refused role change and re-reads the roster', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, admin_id: 1 }),
      members: [
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng', role: 'helper' }),
      ],
      mutate: () => jsonBody({ detail: 'Only the household admin can do this' }, 403),
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Jo Ng')
    await user.click(screen.getByRole('combobox', { name: 'Role for Jo Ng' }))
    await user.click(await screen.findByRole('option', { name: 'Organiser' }))

    // The server's own message, and the roster reloaded so the Select cannot sit there
    // showing a role that was never stored.
    expect(await screen.findByText('Only the household admin can do this')).toBeInTheDocument()
    await waitFor(() => {
      const memberGets = fetchMock.mock.calls.filter(
        ([url, init]) => (init?.method ?? 'GET') === 'GET' && String(url).includes('/members'),
      )
      expect(memberGets.length).toBeGreaterThan(1)
    })
  })

  it('lets the owner transfer ownership to another member', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 1 }),
      members: [
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
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
      members: [makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
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

  it('re-reads the session after leaving, so the sidebar stops promising the role', async () => {
    // Leaving drops a membership. Without the re-read the sidebar keeps whatever that
    // household granted; leaving your last one leaves Tags 404ing with nothing on screen
    // able to clear it. Symmetric with HouseholdCreate, and it is what makes CLAUDE.md's
    // "anything that changes your own memberships must refresh" true rather than aspirational.
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 99 }),
      members: [makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
      mutate: () => jsonBody(undefined, 204),
    })
    const { value } = renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Leave household' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Leave' }))

    expect(await screen.findByText('households-list')).toBeInTheDocument()
    expect(value.refresh).toHaveBeenCalled()
  })

  it('does not re-read the session when leaving fails', async () => {
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 99 }),
      members: [makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
      mutate: () => jsonBody({ detail: 'Transfer ownership first' }, 409),
    })
    const { value } = renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Leave household' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Leave' }))

    expect(await screen.findByText('Transfer ownership first')).toBeInTheDocument()
    expect(value.refresh).not.toHaveBeenCalled()
  })
})
