import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router'
import { toast } from 'sonner'
import Chores from './Chores'
import { renderWithProviders } from '../test/utils'
import { makeChore, makeHousehold, makeTag, makeUser } from '../test/fixtures'
import type { Chore, Household } from '../lib/types'

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
  chores: Chore[]
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
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastChoresGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(
    ([url, init]) =>
      (init?.method ?? 'GET').toUpperCase() === 'GET' &&
      String(url).split('?')[0].endsWith('/api/v1/chores'),
  )
  return String(calls.at(-1)?.[0] ?? '')
}

describe('Chores', () => {
  it('lists chores with household, assignee count, tags and labels', async () => {
    const chore = makeChore({
      id: 7,
      title: 'Scrub the tub',
      household: { id: 4, name: 'Beach House' },
      assignees: [
        makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
        makeUser({ id: 3, first_name: 'Sam', last_name: 'Lee' }),
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
    const chore = makeChore({
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
    const robin = makeUser({ id: 2, first_name: 'Robin', last_name: 'Doe' })
    const chore = makeChore({
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
    const chore = makeChore({
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
    stubFetch({ chores: [makeChore({ title: 'Lonely' })] })
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
    stubFetch({ chores: [makeChore({ id: 7, title: 'Scrub the tub' })] })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/chores/7/edit')
  })

  it('clones a chore into the prefilled create page, carrying its details in router state', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const chore = makeChore({
      id: 7,
      title: 'Scrub the tub',
      description: 'Do it well',
      // Non-default recurrence, so a hardcoded 1 / [] in cloneState would fail here
      // rather than coinciding with the fixture defaults.
      repeats: 'weekly',
      repeat_interval: 3,
      weekdays: [1, 4],
      assignment_type: 'least_done',
      household: { id: 4, name: 'Beach House' },
      assignees: [makeUser({ id: 2 }), makeUser({ id: 3 })],
      tags: [makeTag({ id: 9, name: 'deep-clean' })],
    })
    stubFetch({ chores: [chore] })
    renderWithProviders(
      <Routes>
        <Route path="/chores" element={<Chores />} />
        <Route path="/chores/new" element={<CloneProbe />} />
      </Routes>,
      { authValue: { user: me }, route: '/chores' },
    )

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    const cloneLink = within(row).getByRole('link', { name: 'Clone' })
    expect(cloneLink).toHaveAttribute('href', '/chores/new')

    await user.click(cloneLink)

    const state = JSON.parse(screen.getByTestId('clone-state').textContent!) as {
      clone: Record<string, unknown>
    }
    expect(state.clone).toMatchObject({
      household_id: 4,
      title: 'Scrub the tub',
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

  it('shows a household filter and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      chores: [makeChore({ id: 7, title: 'Scrub the tub' })],
      households: [
        makeHousehold({ id: 1, name: 'Flat 3B' }),
        makeHousehold({ id: 2, name: 'Beach House' }),
      ],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))

    await waitFor(() => expect(lastChoresGet(fetchMock)).toContain('household_id=2'))
  })

  it('hides the household filter when the user has a single household', async () => {
    stubFetch({
      chores: [makeChore({ title: 'Scrub the tub' })],
      households: [makeHousehold({ id: 1, name: 'Flat 3B' })],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('filters by title (debounced) and pushes the term into the query', async () => {
    const fetchMock = stubFetch({
      chores: [makeChore({ id: 7, title: 'Scrub the tub' })],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.type(screen.getByLabelText('Filter by title'), 'tub')

    await waitFor(() => expect(lastChoresGet(fetchMock)).toContain('title=tub'), { timeout: 2000 })
  })

  it('shows the title filter even when the user has a single household', async () => {
    stubFetch({
      chores: [makeChore({ title: 'Scrub the tub' })],
      households: [makeHousehold({ id: 1, name: 'Flat 3B' })],
    })
    renderWithProviders(<Chores />, { authValue: { user: me } })

    await screen.findByText('Scrub the tub')
    expect(screen.getByLabelText('Filter by title')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('pins the actions column to the right edge', async () => {
    stubFetch({ chores: [makeChore({ title: 'Scrub the tub' })] })
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
      chores: [makeChore({ id: 7, title: 'Scrub the tub' })],
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
    const fetchMock = stubFetch({ chores: [makeChore({ id: 7, title: 'Scrub the tub' })] })
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
    stubFetch({ chores: [makeChore({ id: 7, title: 'Scrub the tub' })] })
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
})
