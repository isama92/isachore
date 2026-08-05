import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import History from './History'
import { renderWithProviders, membershipsFor } from '../test/utils'
import { makeHistoryEntry, makeHouseholdMember, makeUser } from '../test/fixtures'
import type { HistoryEntry, HistoryFilterOptions } from '../lib/types'

const me = makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' })
// The signed-in user for undo tests; id 1 matches `me`'s completions.
const authUser = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

function deleteCalls(fetchMock: FetchMock): string[] {
  return fetchMock.mock.calls
    .filter(([, init]) => (init?.method ?? 'GET').toUpperCase() === 'DELETE')
    .map(([url]) => String(url))
}

type FetchMock = ReturnType<typeof vi.fn>

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

function stubFetch(opts: { entries: HistoryEntry[]; options?: HistoryFilterOptions }): FetchMock {
  const options = opts.options ?? {
    households: [{ id: 1, name: 'Test Household', timezone: 'UTC' }],
    members: [me],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/completions/filters')) {
      return jsonBody(options)
    }
    if (method === 'GET' && path.endsWith('/api/v1/completions')) {
      return jsonBody({ items: opts.entries, total: opts.entries.length, page: 1, page_size: 10 })
    }
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastCompletionsGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(
    ([url, init]) =>
      (init?.method ?? 'GET').toUpperCase() === 'GET' &&
      String(url).split('?')[0].endsWith('/api/v1/completions'),
  )
  return String(calls.at(-1)?.[0] ?? '')
}

describe('History', () => {
  it('lists a completed chore with its household and completer', async () => {
    stubFetch({
      entries: [
        makeHistoryEntry({
          id: 7,
          title: 'Scrub the tub',
          household: { id: 4, name: 'Beach House', timezone: 'UTC' },
          completed_by: makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
        }),
      ],
    })
    renderWithProviders(<History />)

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    expect(within(row).getByText('Beach House')).toBeInTheDocument()
    expect(within(row).getByText('Jo Ng')).toBeInTheDocument()
  })

  it("renders completed_at in the zone the closure was judged in, not the household's now", async () => {
    // `days_late` is computed server-side from the snapshot, so the timestamp beside it has to
    // use the same zone. This row is a closure judged in Amsterdam whose household has since
    // moved to Kiritimati (+14): 21:00Z is 23:00 on the 5th there and 11:00 on the 6th here, so
    // rendering in the household's current zone would show "6 Jul" next to "On time" against a
    // 5 July due date.
    stubFetch({
      entries: [
        makeHistoryEntry({
          title: 'Moved household',
          completed_at: '2026-07-05T21:00:00Z',
          completed_timezone: 'Europe/Amsterdam',
          days_late: 0,
          household: { id: 1, name: 'Flat', timezone: 'Pacific/Kiritimati' },
        }),
      ],
    })
    renderWithProviders(<History />)

    const row = (await screen.findByText('Moved household')).closest('tr')!
    expect(row).toHaveTextContent('5 Jul 2026')
    expect(row).not.toHaveTextContent('6 Jul 2026')
  })

  it('falls back to the household zone for a closure with no snapshot', async () => {
    // NULL is what a closure written before the column existed holds; the client then uses the
    // household's current zone, which is the same fallback `closure_zone` applies server-side.
    stubFetch({
      entries: [
        makeHistoryEntry({
          title: 'Old closure',
          completed_at: '2026-07-05T21:00:00Z',
          completed_timezone: null,
          household: { id: 1, name: 'Flat', timezone: 'Pacific/Kiritimati' },
        }),
      ],
    })
    renderWithProviders(<History />)

    const row = (await screen.findByText('Old closure')).closest('tr')!
    expect(row).toHaveTextContent('6 Jul 2026')
  })

  it('shows "N days late" when a completion was overdue', async () => {
    stubFetch({ entries: [makeHistoryEntry({ title: 'Late one', days_late: 3 })] })
    renderWithProviders(<History />)

    const row = (await screen.findByText('Late one')).closest('tr')!
    expect(within(row).getByText('3 days late')).toBeInTheDocument()
  })

  it('shows "On time" for an on-time or early completion', async () => {
    stubFetch({
      entries: [
        makeHistoryEntry({ id: 1, title: 'On the dot', days_late: 0 }),
        makeHistoryEntry({ id: 2, title: 'Ahead of time', days_late: -2 }),
      ],
    })
    renderWithProviders(<History />)

    await screen.findByText('On the dot')
    expect(screen.getAllByText('On time')).toHaveLength(2)
    expect(screen.queryByText(/days late/)).not.toBeInTheDocument()
  })

  it('shows a placeholder rather than a verdict for an unscheduled chore', async () => {
    // null lateness means the chore had no due date to miss (the server decides that). It
    // must not read as "On time", which would claim a punctuality nobody measured. The
    // scheduled row alongside it proves the column still renders a verdict when there is one.
    stubFetch({
      entries: [
        makeHistoryEntry({ id: 1, title: 'Sorted the loft', days_late: null }),
        makeHistoryEntry({ id: 2, title: 'Washed up', days_late: 0 }),
      ],
    })
    renderWithProviders(<History />)

    const unscheduled = (await screen.findByText('Sorted the loft')).closest('tr')!
    expect(within(unscheduled).getByText('—')).toBeInTheDocument()
    expect(within(unscheduled).queryByText('On time')).not.toBeInTheDocument()
    const scheduled = screen.getByText('Washed up').closest('tr')!
    expect(within(scheduled).getByText('On time')).toBeInTheDocument()
  })

  it('shows a placeholder when the completer is unknown', async () => {
    stubFetch({ entries: [makeHistoryEntry({ title: 'Orphaned', completed_by: null })] })
    renderWithProviders(<History />)

    const row = (await screen.findByText('Orphaned')).closest('tr')!
    expect(within(row).getByText('Unknown')).toBeInTheDocument()
  })

  it('shows an empty state when there is no history', async () => {
    stubFetch({ entries: [] })
    renderWithProviders(<History />)

    expect(await screen.findByText('Nothing recorded yet.')).toBeInTheDocument()
  })

  it('filters by person and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      entries: [makeHistoryEntry({ id: 7, title: 'Scrub the tub' })],
      options: {
        households: [{ id: 1, name: 'Test Household', timezone: 'UTC' }],
        members: [me, makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
      },
    })
    renderWithProviders(<History />)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.click(await screen.findByRole('combobox', { name: 'Person' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))

    await waitFor(() => expect(lastCompletionsGet(fetchMock)).toContain('user_id=2'))
  })

  it('filters by household and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      entries: [makeHistoryEntry({ id: 7, title: 'Scrub the tub' })],
      options: {
        households: [
          { id: 1, name: 'Flat 3B', timezone: 'UTC' },
          { id: 2, name: 'Beach House', timezone: 'UTC' },
        ],
        members: [me],
      },
    })
    renderWithProviders(<History />, {
      authValue: { memberships: membershipsFor('deputy', 1, 2) },
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))

    await waitFor(() => expect(lastCompletionsGet(fetchMock)).toContain('household_id=2'))
  })

  it('forgets remembered person and household filters that are no longer offered', async () => {
    localStorage.setItem(
      'isachore-table-history',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { user_id: '98', household_id: '99' },
      }),
    )
    const fetchMock = stubFetch({
      entries: [makeHistoryEntry({ id: 7, title: 'Scrub the tub' })],
      options: {
        households: [
          { id: 1, name: 'Flat 3B', timezone: 'UTC' },
          { id: 2, name: 'Beach House', timezone: 'UTC' },
        ],
        members: [me, makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
      },
    })
    renderWithProviders(<History />)

    // Both ids outlived what made them valid (household left, member removed). Cleared
    // in one setFilters call: two setFilter calls in a tick would lose the first.
    await waitFor(() => {
      const last = lastCompletionsGet(fetchMock)
      expect(last).not.toContain('household_id')
      expect(last).not.toContain('user_id')
    })
  })

  it('hides the person filter when there is a single member', async () => {
    stubFetch({
      entries: [makeHistoryEntry({ title: 'Scrub the tub' })],
      options: { households: [{ id: 1, name: 'Flat 3B', timezone: 'UTC' }], members: [me] },
    })
    renderWithProviders(<History />)

    await screen.findByText('Scrub the tub')
    expect(screen.queryByRole('combobox', { name: 'Person' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('shows an error when loading fails', async () => {
    const fetchMock = vi.fn(async () => jsonBody({ detail: 'boom' }, 500))
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(<History />)

    expect(await screen.findByText('Failed to load history')).toBeInTheDocument()
  })

  // The two rows every undo case below needs: one recorded against the signed-in user, one
  // against a housemate, both in household 1 (which is where the auth fixtures put them).
  const jo = makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })
  const twoRows = [
    makeHistoryEntry({ id: 7, title: 'Mine', completed_by: makeHouseholdMember({ id: 1 }) }),
    makeHistoryEntry({ id: 8, title: 'Theirs', completed_by: jo }),
  ]

  it('shows a deputy undo on their own closure only', async () => {
    // Reading the whole household's history does not carry undoing it: that is
    // organiser-level, and a deputy is one rung below. Their own row keeps the button, which
    // is what makes the missing one about the role rather than about the column.
    stubFetch({ entries: twoRows })
    renderWithProviders(<History />, {
      authValue: { user: authUser, memberships: membershipsFor('deputy', 1) },
    })

    const mineRow = (await screen.findByText('Mine')).closest('tr')!
    const theirsRow = (await screen.findByText('Theirs')).closest('tr')!
    expect(within(mineRow).getByRole('button', { name: 'Undo' })).toBeInTheDocument()
    expect(within(theirsRow).queryByRole('button', { name: /Undo/ })).not.toBeInTheDocument()
  })

  it('lets an organiser undo a housemate’s closure, in the warning colour', async () => {
    // Default memberships make the caller an organiser of household 1, which is where both
    // rows live. Their own row stays plain: the colour marks the difference, so asserting
    // both halves is what pins it to whose closure it is.
    stubFetch({ entries: twoRows })
    renderWithProviders(<History />, { authValue: { user: authUser } })

    const mineRow = (await screen.findByText('Mine')).closest('tr')!
    const theirsRow = (await screen.findByText('Theirs')).closest('tr')!
    expect(within(mineRow).getByRole('button', { name: 'Undo' })).not.toHaveClass('text-warning')
    // The hover half is asserted too: the ghost variant carries hover:text-foreground, so
    // without it the colour is lost on the one row the colour is the whole point of.
    expect(within(theirsRow).getByRole('button', { name: "Undo Jo Ng's entry" })).toHaveClass(
      'text-warning',
      'hover:text-warning',
    )
  })

  it('names the person in the confirmation, and undoes their closure', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = stubFetch({ entries: twoRows })
    renderWithProviders(<History />, { authValue: { user: authUser } })

    const theirsRow = (await screen.findByText('Theirs')).closest('tr')!
    await user.click(within(theirsRow).getByRole('button', { name: "Undo Jo Ng's entry" }))
    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.getByText(/This entry was recorded by Jo Ng\./)).toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Undo entry' }))

    await waitFor(() =>
      expect(deleteCalls(fetchMock).some((u) => u.includes('/api/v1/completions/8'))).toBe(true),
    )
  })

  it('treats a closure with no known completer as somebody else’s', async () => {
    // `completed_by: null` is a hard-deleted account. It used to render no undo at all; now an
    // organiser gets one, and it has to come out as somebody else's - warning colour and its
    // own copy, since there is no name to put in the usual sentence.
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    stubFetch({
      entries: [makeHistoryEntry({ id: 9, title: 'Orphaned', completed_by: null })],
    })
    renderWithProviders(<History />, { authValue: { user: authUser } })

    const row = (await screen.findByText('Orphaned')).closest('tr')!
    const button = within(row).getByRole('button', { name: "Undo somebody else's entry" })
    expect(button).toHaveClass('text-warning')
    await user.click(button)
    expect(
      within(await screen.findByRole('alertdialog')).getByText(/account no longer exists/),
    ).toBeInTheDocument()
  })

  it('offers a helper no undo on a housemate’s closure', async () => {
    // A helper's own rows are all they see, but the guard is on the row rather than on the
    // list, so a housemate's row reaching them must still refuse.
    stubFetch({ entries: twoRows })
    renderWithProviders(<History />, {
      authValue: { user: authUser, memberships: membershipsFor('helper', 1) },
    })

    const mineRow = (await screen.findByText('Mine')).closest('tr')!
    const theirsRow = (await screen.findByText('Theirs')).closest('tr')!
    expect(within(mineRow).getByRole('button', { name: 'Undo' })).toBeInTheDocument()
    expect(within(theirsRow).queryByRole('button', { name: /Undo/ })).not.toBeInTheDocument()
  })

  it('does not offer undo in a household the caller only helps in', async () => {
    // The organiser rule is per household, not "organiser anywhere": household 2's row must
    // not inherit the reach household 1 grants.
    stubFetch({
      entries: [
        makeHistoryEntry({
          id: 8,
          title: 'Theirs',
          completed_by: jo,
          household: { id: 2, name: 'Beach House', timezone: 'UTC' },
        }),
      ],
      options: {
        households: [
          { id: 1, name: 'Test Household', timezone: 'UTC' },
          { id: 2, name: 'Beach House', timezone: 'UTC' },
        ],
        members: [me, jo],
      },
    })
    renderWithProviders(<History />, {
      authValue: {
        user: authUser,
        memberships: [
          { household_id: 1, role: 'organiser', owned: false },
          { household_id: 2, role: 'helper', owned: false },
        ],
      },
    })

    const row = (await screen.findByText('Theirs')).closest('tr')!
    expect(within(row).queryByRole('button', { name: /Undo/ })).not.toBeInTheDocument()
  })

  it('undoes a completion after confirming, calling DELETE and reloading', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    const fetchMock = stubFetch({
      entries: [
        makeHistoryEntry({ id: 7, title: 'Mine', completed_by: makeHouseholdMember({ id: 1 }) }),
      ],
    })
    renderWithProviders(<History />, { authValue: { user: authUser } })

    const row = (await screen.findByText('Mine')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Undo' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Undo entry',
      }),
    )

    await waitFor(() =>
      expect(deleteCalls(fetchMock).some((u) => u.includes('/api/v1/completions/7'))).toBe(true),
    )
    expect(toastSpy).toHaveBeenCalledWith('Entry undone')
  })

  it('does not undo when the dialog is cancelled', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = stubFetch({
      entries: [
        makeHistoryEntry({ id: 7, title: 'Mine', completed_by: makeHouseholdMember({ id: 1 }) }),
      ],
    })
    renderWithProviders(<History />, { authValue: { user: authUser } })

    const row = (await screen.findByText('Mine')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Undo' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }),
    )

    expect(deleteCalls(fetchMock)).toHaveLength(0)
  })

  it('offers every household the filter payload lists, helper households included', async () => {
    // The picker is deliberately NOT narrowed by role. It used to be, back when the list was
    // scoped to deputy+ and a helper household was a dead option; now such a household yields
    // the caller's own closures, so it is a live one.
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    stubFetch({
      entries: [makeHistoryEntry({ id: 1, title: 'Scrub the tub' })],
      options: {
        households: [
          { id: 1, name: 'Flat 3B', timezone: 'UTC' },
          { id: 2, name: 'Beach House', timezone: 'UTC' },
        ],
        members: [me],
      },
    })
    renderWithProviders(<History />, {
      authValue: {
        user: authUser,
        memberships: [
          { household_id: 1, role: 'deputy', owned: false },
          { household_id: 2, role: 'helper', owned: false },
        ],
      },
    })

    await screen.findByText('Scrub the tub')
    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    expect(await screen.findByRole('option', { name: 'Beach House' })).toBeInTheDocument()
  })

  it('renders no filter bar at all for a helper everywhere', async () => {
    // Their own closures are the whole list, so there is nothing to slice: every Select would
    // be one option over a list already as narrow as it goes.
    stubFetch({
      entries: [makeHistoryEntry({ id: 1, title: 'Scrub the tub' })],
      options: {
        households: [
          { id: 1, name: 'Flat 3B', timezone: 'UTC' },
          { id: 2, name: 'Beach House', timezone: 'UTC' },
        ],
        members: [me, makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
      },
    })
    renderWithProviders(<History />, {
      authValue: { user: authUser, memberships: membershipsFor('helper', 1, 2) },
    })

    // The row is the positive half: the page works, it is the bar that is gone. Both option
    // lists have two entries, so each Select would render if it were not for the role.
    await screen.findByText('Scrub the tub')
    expect(screen.queryByRole('combobox', { name: 'Outcome' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Person' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('clears remembered filters with a hidden bar even when the options fail to load', async () => {
    // The prune reads no payload, so it must not ride on that request: a 5xx there would
    // otherwise leave a helper with filters applied, no Select to clear them, and no error
    // text, since the hook only forgets stored settings on a 400/422.
    localStorage.setItem(
      'isachore-table-history',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { user_id: '2', household_id: '1', outcome: 'skipped' },
      }),
    )
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split('?')[0]
      if (path.endsWith('/api/v1/completions/filters')) return jsonBody({ detail: 'boom' }, 500)
      if ((init?.method ?? 'GET').toUpperCase() === 'GET') {
        return jsonBody({ items: [], total: 0, page: 1, page_size: 10 })
      }
      return jsonBody(undefined, 204)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(<History />, {
      authValue: { user: authUser, memberships: membershipsFor('helper', 1) },
    })

    await waitFor(() => {
      const query = lastCompletionsGet(fetchMock)
      expect(query).not.toContain('user_id')
      expect(query).not.toContain('household_id')
      expect(query).not.toContain('outcome')
    })
  })

  it('clears every remembered filter when the bar is hidden', async () => {
    // A demotion to helper-everywhere leaves stored filters with nothing on screen able to
    // clear them: the hook only forgets storage on a 400/422, and these merely return less.
    localStorage.setItem(
      'isachore-table-history',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { user_id: '2', household_id: '1', outcome: 'skipped' },
      }),
    )
    const fetchMock = stubFetch({
      entries: [makeHistoryEntry({ id: 1, title: 'Scrub the tub' })],
    })
    renderWithProviders(<History />, {
      authValue: { user: authUser, memberships: membershipsFor('helper', 1) },
    })

    await waitFor(() => {
      const query = lastCompletionsGet(fetchMock)
      expect(query).not.toContain('user_id')
      expect(query).not.toContain('household_id')
      expect(query).not.toContain('outcome')
    })
  })
  it('badges the skipped rows and only those', async () => {
    stubFetch({
      entries: [
        makeHistoryEntry({ id: 7, title: 'Scrub the tub', skipped: true, days_late: null }),
        makeHistoryEntry({ id: 8, title: 'Take the bins out', skipped: false, days_late: 2 }),
      ],
    })
    renderWithProviders(<History />, { authValue: { user: authUser } })

    const skippedRow = (await screen.findByText('Scrub the tub')).closest('tr')!
    expect(within(skippedRow).getByText('Skipped')).toBeInTheDocument()
    // The lateness column already says nothing for it, since days_late comes back null.
    expect(within(skippedRow).getByText('—')).toBeInTheDocument()

    const completedRow = screen.getByText('Take the bins out').closest('tr')!
    expect(within(completedRow).queryByText('Skipped')).not.toBeInTheDocument()
    expect(within(completedRow).getByText('2 days late')).toBeInTheDocument()
  })

  it('filters by outcome and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      entries: [makeHistoryEntry({ id: 7, title: 'Scrub the tub' })],
    })
    renderWithProviders(<History />, { authValue: { user: authUser } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    // Offered even here, with a single member and a single household: the payload says
    // nothing about whether any skips exist, so there is nothing to hide it on.
    await user.click(await screen.findByRole('combobox', { name: 'Outcome' }))
    await user.click(await screen.findByRole('option', { name: 'Skipped only' }))

    await waitFor(() => expect(lastCompletionsGet(fetchMock)).toContain('outcome=skipped'))
  })
})
