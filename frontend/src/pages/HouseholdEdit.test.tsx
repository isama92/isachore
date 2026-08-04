import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import HouseholdEdit from './HouseholdEdit'
import { membershipsFor, renderWithProviders } from '../test/utils'
import { makeHousehold, makeHouseholdMemberWithRole, makeUser } from '../test/fixtures'
import type { Household, HouseholdMemberWithRole } from '../lib/types'
import type { AuthContextValue } from '../auth/context'

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

function renderEdit(fetchMock: FetchMock, authValue: Partial<AuthContextValue> = {}) {
  vi.stubGlobal('fetch', fetchMock)
  return renderWithProviders(
    <Routes>
      <Route path="/households/:id/edit" element={<HouseholdEdit />} />
      <Route path="/households" element={<div>households-list</div>} />
    </Routes>,
    // Household 5 throughout, so a test's `memberships` must name that id to grant a role in
    // the household under test.
    {
      authValue: { user: me, memberships: membershipsFor('organiser', 5), ...authValue },
      route: '/households/5/edit',
    },
  )
}

// Picking a role stages it behind a confirmation, like deactivating a user on the admin
// table: this walks the whole gesture, so a test that forgets the dialog fails loudly rather
// than silently asserting no PATCH.
async function chooseRole(user: ReturnType<typeof userEvent.setup>, name: string, role: string) {
  await user.click(screen.getByRole('combobox', { name: `Role for ${name}` }))
  await user.click(await screen.findByRole('option', { name: role }))
  const dialog = within(await screen.findByRole('alertdialog'))
  await user.click(dialog.getByRole('button', { name: 'Change role' }))
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
  // The role cell is `assignableRoles(viewer, target)`: three inputs, so the cases below vary
  // one at a time - who is looking (owner / organiser / deputy / helper) against what they
  // are looking at (the owner's row / an organiser / a deputy or helper). A case that moved
  // two at once would pass on whichever branch survived.

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
    await chooseRole(user, 'Jo Ng', 'Deputy')

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([url, init]) => init?.method === 'PATCH' && String(url).endsWith('/members/2'),
      )
      expect(patch).toBeTruthy()
      expect(JSON.parse(String(patch![1]?.body))).toEqual({ role: 'deputy' })
    })
  })

  it('reads Admin on the owner’s row, once, and offers no control there', async () => {
    // Three things at once, because they are one design decision: the owner's role is not
    // editable by anybody (this is their OWN view, so the target rule is the only thing
    // stopping it), the cell says "Admin" rather than "Organiser", and it says it once - the
    // badge that used to sit beside the name is gone, since two labels for one fact read as
    // two facts.
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
    expect(within(ownerRow).getAllByText('Admin')).toHaveLength(1)
    expect(within(ownerRow).queryByText('Organiser')).not.toBeInTheDocument()
    // And the other row proves the view is otherwise editable.
    expect(screen.getByRole('combobox', { name: 'Role for Jo Ng' })).toBeInTheDocument()
  })

  it('shows a helper every role as a badge', async () => {
    // The row is NOT the owner's, so the viewer's own role is the only thing keeping it
    // read-only - which is why this passes helper memberships explicitly rather than relying
    // on being a non-owner, as it used to. An organiser is a non-owner too, and does get a
    // control here (see the organiser cases below).
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, admin_id: 99 }),
      members: [
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng', role: 'helper' }),
      ],
    })
    renderEdit(fetchMock, { memberships: membershipsFor('helper', 5) })

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
    await chooseRole(user, 'Jo Ng', 'Organiser')

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

  it('re-reads the session after transferring, so the sidebar stops offering Logs', async () => {
    // Handing the household on drops the caller's own ownership, and the Logs item is gated on
    // exactly that. Without the re-read an ex-owner keeps the item and reaches a page the API
    // empties, with nothing on screen at fault. The fifth of the pinned refresh() cases.
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 1 }),
      members: [
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
      ],
      mutate: () => jsonBody(makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 2 })),
    })
    const { value } = renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Jo Ng')
    await user.click(screen.getByRole('combobox', { name: 'Household admin' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    const group = within(screen.getByRole('group', { name: 'Household admin' }))
    await user.click(await group.findByRole('button', { name: 'Save' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Transfer' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
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
    // The stored zone rides along unchanged; the fixture household is on UTC.
    expect(JSON.parse(String(patch![1]?.body))).toEqual({ name: 'New', timezone: 'UTC' })
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

  // --- the organiser view ------------------------------------------------
  //
  // An organiser is a non-owner, so they land on the read-only branch: the household itself
  // stays text, but they share the *people* work.

  const ORGANISER_ROSTER = [
    makeHouseholdMemberWithRole({ id: 99, first_name: 'Olive', last_name: 'Owner' }),
    makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
    makeHouseholdMemberWithRole({ id: 2, first_name: 'Dee', last_name: 'Puty', role: 'deputy' }),
    makeHouseholdMemberWithRole({ id: 3, first_name: 'Hal', last_name: 'Per', role: 'helper' }),
  ]

  function organiserMocks(mutate?: (method: string, url: string) => Response) {
    // admin_id 99 is somebody else, so `me` (id 1) is an organiser and not the owner.
    return stubFetch({
      household: makeHousehold({ id: 5, name: 'Flat 3B', admin_id: 99 }),
      members: ORGANISER_ROSTER,
      mutate,
    })
  }

  it('offers an organiser deputy and helper only, and never on an organiser row', async () => {
    renderEdit(organiserMocks())
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Hal Per')
    // The owner and the organiser peer (themselves) are badges...
    const table = screen.getByRole('table')
    expect(
      within(within(table).getByText('Olive Owner').closest('tr')!).queryByRole('combobox'),
    ).not.toBeInTheDocument()
    expect(
      within(within(table).getByText('Alex Kim').closest('tr')!).queryByRole('combobox'),
    ).not.toBeInTheDocument()

    // ...and the deputy and helper rows are editable, with `organiser` absent from the options.
    await user.click(screen.getByRole('combobox', { name: 'Role for Hal Per' }))
    const options = (await screen.findAllByRole('option')).map((o) => o.textContent)
    expect(options).toEqual(['Deputy', 'Helper'])
  })

  it('lets an organiser set a role, and shows them the invitations', async () => {
    const fetchMock = organiserMocks(() =>
      jsonBody(
        makeHouseholdMemberWithRole({ id: 3, first_name: 'Hal', last_name: 'Per', role: 'deputy' }),
      ),
    )
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Hal Per')
    await chooseRole(user, 'Hal Per', 'Deputy')

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([url, init]) => init?.method === 'PATCH' && String(url).endsWith('/members/3'),
      )
      expect(patch).toBeTruthy()
      expect(JSON.parse(String(patch![1]?.body))).toEqual({ role: 'deputy' })
    })
    // Inviting moved to organiser-level alongside role-setting: both are managing people.
    expect(screen.getByRole('button', { name: 'Add member' })).toBeInTheDocument()
  })

  it('keeps the household itself, and removing members, out of an organiser’s reach', async () => {
    renderEdit(organiserMocks())

    await screen.findByText('Hal Per')
    expect(screen.queryByDisplayValue('Flat 3B')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household admin' })).not.toBeInTheDocument()
  })

  it('shows a deputy every role as a badge, and no invitations', async () => {
    // Same page, same roster, one role lower: the only difference is `memberships`, which is
    // what makes this about the role rather than about ownership.
    renderEdit(organiserMocks(), { memberships: membershipsFor('deputy', 5) })

    await screen.findByText('Hal Per')
    // Named queries: an unnamed `combobox` also matches the table's own "Rows per page" select.
    for (const name of ['Role for Hal Per', 'Role for Dee Puty']) {
      expect(screen.queryByRole('combobox', { name })).not.toBeInTheDocument()
    }
    expect(within(screen.getByRole('table')).getByText('Helper')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add member' })).not.toBeInTheDocument()
    // ...but they can still leave.
    expect(screen.getByRole('button', { name: 'Leave household' })).toBeInTheDocument()
  })

  it('sends nothing when a role change is cancelled, and keeps the stored role showing', async () => {
    // The point of the confirmation. Cancelling needs no revert because the Select is controlled
    // by `member.role`, which never moved - so the trigger still reads Helper afterwards, and
    // that is what this asserts rather than trusting the absence of a request alone.
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, admin_id: 1 }),
      members: [
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng', role: 'helper' }),
      ],
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Jo Ng')
    await user.click(screen.getByRole('combobox', { name: 'Role for Jo Ng' }))
    await user.click(await screen.findByRole('option', { name: 'Organiser' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
    expect(screen.getByRole('combobox', { name: 'Role for Jo Ng' })).toHaveTextContent('Helper')
  })

  it('names the member and the new role in the confirmation', async () => {
    // Both interpolations, because a dialog that says "Give  the  role?" would still pass a
    // test that only looked for the dialog.
    const fetchMock = stubFetch({
      household: makeHousehold({ id: 5, admin_id: 1 }),
      members: [
        makeHouseholdMemberWithRole({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
        makeHouseholdMemberWithRole({ id: 2, first_name: 'Jo', last_name: 'Ng', role: 'helper' }),
      ],
    })
    renderEdit(fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Jo Ng')
    await user.click(screen.getByRole('combobox', { name: 'Role for Jo Ng' }))
    await user.click(await screen.findByRole('option', { name: 'Deputy' }))

    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.getByText('Give Jo Ng the Deputy role?')).toBeInTheDocument()
  })
})
