import { describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router'
import { toast } from 'sonner'
import Chores from './Chores'
import { renderWithProviders, membershipsFor } from '../test/utils'
import { formatDate, formatDateTime } from '../lib/chores'
import {
  makeChore,
  makeChoreRow,
  makeHousehold,
  makeHouseholdMember,
  makeTag,
  makeUser,
} from '../test/fixtures'
import type { Chore, ChoreListRow, Household } from '../lib/types'

// Reads the router state pushed by the clone action so a test can assert it.
function CloneProbe() {
  const location = useLocation()
  return <pre data-testid="clone-state">{JSON.stringify(location.state)}</pre>
}

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

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
  chores: ChoreListRow[]
  // The chore GET /chores/{id} answers with. The clone action reads the description from
  // there, since the list rows no longer carry it.
  detail?: Chore
  households?: Household[]
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const households = opts.households ?? [makeHousehold({ id: 1, name: 'Test Household' })]
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/households')) {
      return jsonBody({ items: households, total: households.length, page: 1, page_size: 100 })
    }
    if (method === 'GET' && path.endsWith('/api/v1/chores')) {
      return jsonBody({ items: opts.chores, total: opts.chores.length, page: 1, page_size: 20 })
    }
    if (method === 'GET' && /\/api\/v1\/chores\/\d+$/.test(path)) {
      return opts.detail ? jsonBody(opts.detail) : jsonBody({ detail: 'Chore not found' }, 404)
    }
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function choresGets(fetchMock: FetchMock): string[] {
  return fetchMock.mock.calls
    .filter(
      ([url, init]) =>
        (init?.method ?? 'GET').toUpperCase() === 'GET' &&
        String(url).split('?')[0].endsWith('/api/v1/chores'),
    )
    .map(([url]) => String(url))
}

function lastChoresGet(fetchMock: FetchMock): string {
  return choresGets(fetchMock).at(-1) ?? ''
}

describe('Chores', () => {
  it('lists chores with household, assignee count, tags and labels', async () => {
    const chore = makeChoreRow({
      id: 7,
      title: 'Scrub the tub',
      household: { id: 4, name: 'Beach House' },
      assignees: [
        makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
        makeHouseholdMember({ id: 3, first_name: 'Sam', last_name: 'Lee' }),
      ],
      tags: [makeTag({ id: 3, name: 'deep-clean', color: '#0d9488' })],
      repeats: 'daily',
      assignment_type: 'least_done',
    })
    stubFetch({ chores: [chore] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    expect(within(row).getByText('Beach House')).toBeInTheDocument()
    // Assignees are shown as a count, not by name.
    expect(within(row).getByText('2')).toBeInTheDocument()
    expect(within(row).queryByText('Jo Ng')).not.toBeInTheDocument()
    expect(within(row).getByText('deep-clean')).toBeInTheDocument()
    expect(within(row).getByText('Daily')).toBeInTheDocument()
    expect(within(row).getByText('Least done')).toBeInTheDocument()
  })

  it('spells out the interval and pinned weekdays in the repeats column', async () => {
    const chore = makeChoreRow({
      id: 9,
      title: 'Washing machine',
      repeats: 'weekly',
      repeat_interval: 2,
      weekdays: [1, 4],
    })
    stubFetch({ chores: [chore] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Washing machine')).closest('tr')!
    expect(within(row).getByText('Every 2 weeks (Tue, Fri)')).toBeInTheDocument()
  })

  it('shows the current assignee next to the assignment strategy', async () => {
    const robin = makeHouseholdMember({ id: 2, first_name: 'Robin', last_name: 'Doe' })
    const chore = makeChoreRow({
      id: 8,
      title: 'Water plants',
      assignment_type: 'alphabetical',
      assignees: [robin],
      current_assignee: robin,
    })
    stubFetch({ chores: [chore] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Water plants')).closest('tr')!
    expect(row).toHaveTextContent('Alphabetical')
    expect(row).toHaveTextContent('Robin')
  })

  it('collapses many tags to the first plus an "and N more" hover tooltip', async () => {
    const chore = makeChoreRow({
      id: 8,
      title: 'Big job',
      tags: [
        makeTag({ id: 3, name: 'deep-clean', color: '#0d9488' }),
        makeTag({ id: 4, name: 'shared', color: '#7c6bf0' }),
      ],
    })
    stubFetch({ chores: [chore] })
    renderWithProviders(<Chores />, { authValue: { user: me } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    const row = (await screen.findByText('Big job')).closest('tr')!
    expect(within(row).getByText('deep-clean')).toBeInTheDocument()
    expect(within(row).getByText('and 1 more')).toBeInTheDocument()
    // The extra tag is hidden in the row until the field is hovered.
    expect(within(row).queryByText('shared')).not.toBeInTheDocument()

    await user.hover(within(row).getByText('and 1 more').closest('button')!)
    const tooltip = await screen.findByRole('tooltip')
    expect(within(tooltip).getByText('deep-clean')).toBeInTheDocument()
    expect(within(tooltip).getByText('shared')).toBeInTheDocument()
  })

  it('shows placeholders for an unassigned, untagged chore', async () => {
    stubFetch({ chores: [makeChoreRow({ title: 'Lonely' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    expect(await screen.findByText('Lonely')).toBeInTheDocument()
    expect(screen.getByText('Unassigned')).toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
  })

  it('shows an empty state when there are no chores', async () => {
    stubFetch({ chores: [] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    expect(await screen.findByText('No chores yet.')).toBeInTheDocument()
  })

  it('links each row to its edit page', async () => {
    stubFetch({ chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/chores/7/edit')
  })

  it('clones a chore into the prefilled create page, carrying its details in router state', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const details = {
      id: 7,
      title: 'Scrub the tub',
      // Non-default recurrence, so a hardcoded 1 / [] in cloneState would fail here
      // rather than coinciding with the fixture defaults.
      repeats: 'weekly' as const,
      repeat_interval: 3,
      weekdays: [1, 4],
      assignment_type: 'least_done' as const,
      household: { id: 4, name: 'Beach House' },
      assignees: [makeHouseholdMember({ id: 2 }), makeHouseholdMember({ id: 3 })],
      tags: [makeTag({ id: 9, name: 'deep-clean' })],
    }
    // The row says only that a description exists; the description itself comes back from
    // GET /chores/{id}, which is what the clone must read it from.
    stubFetch({
      chores: [makeChoreRow({ ...details, has_description: true })],
      detail: makeChore({ ...details, description: 'Do it well' }),
    })
    renderWithProviders(
      <Routes>
        <Route path="/chores" element={<Chores />} />
        <Route path="/chores/new" element={<CloneProbe />} />
      </Routes>,
      { authValue: { user: me }, route: '/chores' },
    )

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Clone' }))

    const probe = await screen.findByTestId('clone-state')
    const state = JSON.parse(probe.textContent!) as { clone: Record<string, unknown> }
    expect(state.clone).toMatchObject({
      household_id: 4,
      title: 'Scrub the tub',
      // The whole point: dropped from the list payload, so it has to be fetched.
      description: 'Do it well',
      repeats: 'weekly',
      assignment_type: 'least_done',
      assignee_ids: [2, 3],
      tag_ids: [9],
      // Carried, or the copy silently loses its schedule.
      repeat_interval: 3,
      weekdays: [1, 4],
    })
  })

  it('stays put and explains itself when the source chore cannot be read', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    // No `detail`, so the stub 404s the chore read - the chore was deleted by a housemate
    // between the list loading and the click.
    stubFetch({ chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })] })
    renderWithProviders(
      <Routes>
        <Route path="/chores" element={<Chores />} />
        <Route path="/chores/new" element={<CloneProbe />} />
      </Routes>,
      { authValue: { user: me }, route: '/chores' },
    )

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Clone' }))

    expect(await screen.findByText('Chore not found')).toBeInTheDocument()
    expect(screen.queryByTestId('clone-state')).not.toBeInTheDocument()
  })

  it('sorts by creation date, newest first, by default', async () => {
    const fetchMock = stubFetch({ chores: [makeChoreRow({ title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    const firstGet = lastChoresGet(fetchMock)
    expect(firstGet).toContain('sort_by=created_at')
    expect(firstGet).toContain('sort_dir=desc')
    expect(screen.getByRole('columnheader', { name: /Created/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
    // Start keeps its own server-side sort; 'none' (not absent) is what says the
    // column is still sortable, just not the one currently sorted.
    expect(screen.getByRole('columnheader', { name: /Start/ })).toHaveAttribute('aria-sort', 'none')
  })

  it('shows when each chore was created, including the time', async () => {
    const chore = makeChoreRow({
      title: 'Scrub the tub',
      created_at: '2026-03-04T09:30:00Z',
      start_date: '2026-07-16',
    })
    stubFetch({ chores: [chore] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    // Expected text comes from the same helper rather than a literal: the cell renders
    // in the viewer's timezone and the suite pins none. The two dates are deliberately
    // months apart, so this fails if the column renders start_date by mistake.
    expect(within(row).getByText(formatDateTime(chore.created_at))).toBeInTheDocument()
    expect(within(row).getByText(formatDate(chore.start_date!))).toBeInTheDocument()
  })

  it('places a placeholder in Start for an unscheduled chore', async () => {
    // An unscheduled chore has no start date at all. The Repeats cell beside it already
    // says "Unscheduled", so the date cell only needs to not render an empty gap.
    stubFetch({
      chores: [makeChoreRow({ title: 'Sort the loft', repeats: 'manual', start_date: null })],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Sort the loft')).closest('tr')!
    expect(within(row).getByText('Unscheduled')).toBeInTheDocument()
    expect(within(row).getByText('—')).toBeInTheDocument()
  })

  it('sorts ascending when the Created header is clicked', async () => {
    const fetchMock = stubFetch({ chores: [makeChoreRow({ title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.click(screen.getByRole('button', { name: /Created/ }))

    await waitFor(() => expect(lastChoresGet(fetchMock)).toContain('sort_dir=asc'))
    expect(lastChoresGet(fetchMock)).toContain('sort_by=created_at')
  })

  it('pre-fills the title input from a remembered text filter and keeps it', async () => {
    localStorage.setItem(
      'isachore-table-chores',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { household_id: '', title: 'tub' },
      }),
    )
    const fetchMock = stubFetch({ chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    // The input seeds from the restored filter rather than '', which is what stops the
    // 300ms debounce from firing on mount and wiping the very value it restored. A
    // future text filter initialised from '' would silently do exactly that.
    expect(screen.getByLabelText('Filter by title')).toHaveValue('tub')
    expect(lastChoresGet(fetchMock)).toContain('title=tub')
    // Still there after the debounce window has had time to fire.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400))
    })
    expect(lastChoresGet(fetchMock)).toContain('title=tub')
    expect(screen.getByLabelText('Filter by title')).toHaveValue('tub')
  })

  it('keeps a remembered household filter that is still valid', async () => {
    localStorage.setItem(
      'isachore-table-chores',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { household_id: '2', title: '' },
      }),
    )
    const fetchMock = stubFetch({
      chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })],
      households: [
        makeHousehold({ id: 1, name: 'Flat 3B' }),
        makeHousehold({ id: 2, name: 'Beach House' }),
      ],
    })
    renderWithProviders(<Chores />, {
      authValue: { user: me, memberships: membershipsFor('organiser', 1, 2) },
    })

    // The select renders only once the households have loaded, so this is the prune
    // having had its chance to run.
    await screen.findByRole('combobox', { name: 'Household' })
    // Then settle: a prune navigates, which would refetch. Asserting the query
    // straight away would pass whether or not the filter was wrongly cleared, so
    // "still exactly one request" is what actually pins this.
    await act(async () => {})
    expect(choresGets(fetchMock)).toHaveLength(1)
    expect(lastChoresGet(fetchMock)).toContain('household_id=2')
    expect(screen.getByRole('combobox', { name: 'Household' })).toHaveTextContent('Beach House')
  })

  it('forgets a remembered household filter the user can no longer pick', async () => {
    localStorage.setItem(
      'isachore-table-chores',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { household_id: '99', title: '' },
      }),
    )
    const fetchMock = stubFetch({
      chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })],
      households: [
        makeHousehold({ id: 1, name: 'Flat 3B' }),
        makeHousehold({ id: 2, name: 'Beach House' }),
      ],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    // Household 99 is gone (left, deleted, membership revoked). Left in place it would
    // filter the list to nothing behind a blank select, with no way back.
    await waitFor(() => expect(lastChoresGet(fetchMock)).not.toContain('household_id'))
  })

  it('shows a household filter and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })],
      households: [
        makeHousehold({ id: 1, name: 'Flat 3B' }),
        makeHousehold({ id: 2, name: 'Beach House' }),
      ],
    })
    renderWithProviders(<Chores />, {
      authValue: { user: me, memberships: membershipsFor('organiser', 1, 2) },
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))

    await waitFor(() => expect(lastChoresGet(fetchMock)).toContain('household_id=2'))
  })

  it('hides the household filter when the user has a single household', async () => {
    stubFetch({
      chores: [makeChoreRow({ title: 'Scrub the tub' })],
      households: [makeHousehold({ id: 1, name: 'Flat 3B' })],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('filters by title (debounced) and pushes the term into the query', async () => {
    const fetchMock = stubFetch({
      chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.type(screen.getByLabelText('Filter by title'), 'tub')

    await waitFor(() => expect(lastChoresGet(fetchMock)).toContain('title=tub'), { timeout: 2000 })
  })

  it('shows the title filter even when the user has a single household', async () => {
    stubFetch({
      chores: [makeChoreRow({ title: 'Scrub the tub' })],
      households: [makeHousehold({ id: 1, name: 'Flat 3B' })],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    expect(screen.getByLabelText('Filter by title')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('pins the actions column to the right edge', async () => {
    stubFetch({ chores: [makeChoreRow({ title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    // .pinned-col is what keeps the buttons visible while the row scrolls.
    expect(screen.getByRole('columnheader', { name: 'Actions' }).className).toContain('pinned-col')
  })

  it('soft-deletes a chore after confirming in the dialog and reloads', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    let deleted = ''
    const fetchMock = stubFetch({
      chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })],
      mutate: (method, url) => {
        if (method === 'DELETE') deleted = url
        return jsonBody(undefined, 204)
      },
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Delete' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete chore' }),
    )

    await waitFor(() => expect(deleted).toContain('/api/v1/chores/7'))
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true)
    expect(toastSpy).toHaveBeenCalledWith('Chore deleted')
  })

  it('does not delete when the dialog is cancelled', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = stubFetch({ chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Delete' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }),
    )

    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('does not use the word "permanently" in the delete dialog', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    stubFetch({ chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Delete' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.queryByText(/permanently/i)).not.toBeInTheDocument()
  })

  it('shows an error when loading fails', async () => {
    const fetchMock = vi.fn(async () => jsonBody({ detail: 'boom' }, 500))
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(<Chores />, { authValue: { user: me } })

    expect(await screen.findByText('Failed to load chores')).toBeInTheDocument()
  })

  it('offers only the households the user organises', async () => {
    // The list itself is server-scoped to organised households, so a deputy household in this
    // picker is a dead option: choosing it filters an already-filtered list down to nothing
    // behind a blank Select. With one left the Select hides (it renders above one).
    const fetchMock = stubFetch({
      chores: [makeChoreRow({ id: 7, title: 'Scrub the tub' })],
      households: [
        makeHousehold({ id: 1, name: 'Flat 3B' }),
        makeHousehold({ id: 2, name: 'Beach House' }),
      ],
    })
    renderWithProviders(<Chores />, {
      authValue: {
        user: me,
        memberships: [
          { household_id: 1, role: 'organiser' },
          { household_id: 2, role: 'deputy' },
        ],
      },
    })

    await screen.findByText('Scrub the tub')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    // The positive half: the household list really loaded, so the missing Select is the
    // filter's doing rather than a fixture that never answered.
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/v1/households'))).toBe(
      true,
    )
  })
})
