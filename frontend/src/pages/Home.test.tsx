import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Home from './Home'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeChore, makeDueChore, makeHouseholdMember, makeUser } from '../test/fixtures'
import type { DueChore, HistoryFilterOptions } from '../lib/types'

const HOME = /\/api\/v1\/home/
const FILTERS = '/api/v1/completions/filters'
const COMPLETE = /\/api\/v1\/chores\/\d+\/complete/
const SKIP = /\/api\/v1\/chores\/\d+\/skip/

// Every row carries two buttons naming its chore now (Skip and Done), so a query by title
// alone is ambiguous: these anchor on the action prefix from the locale string.

function homeBody(done: number, total: number, items: DueChore[]) {
  return { progress: { done_today: done, total_today: total }, items }
}

// A single household + member keeps the filter bar hidden (it only renders when
// there is more than one of either).
const SOLO_OPTIONS: HistoryFilterOptions = {
  households: [{ id: 1, name: 'Test Household' }],
  members: [makeHouseholdMember({ id: 1 })],
}

// Two of each so both filters render.
const MULTI_OPTIONS: HistoryFilterOptions = {
  households: [
    { id: 1, name: 'Flat A' },
    { id: 2, name: 'Flat B' },
  ],
  members: [
    makeHouseholdMember({ id: 1, first_name: 'Me', last_name: 'Myself' }),
    makeHouseholdMember({ id: 2, first_name: 'Bram', last_name: 'Bakker' }),
  ],
}

// A due chore for the section tests, keeping next_due and days_until_due in
// step (the server derives both from the same value).
function nextDue(id: number, title: string, days: number, date: string): DueChore {
  return makeDueChore({
    id,
    title,
    days_until_due: days,
    next_due: `${date}T09:00:00Z`,
    status: days < 0 ? 'overdue' : days === 0 ? 'today' : 'soon',
  })
}

function homeGets(fetchMock: ReturnType<typeof mockFetch>): string[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => HOME.test(String(url)) && (init?.method ?? 'GET') === 'GET')
    .map(([url]) => String(url))
}

describe('Home', () => {
  it('renders the progress and status-coded due rows', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(5, 8, [
          makeDueChore({
            id: 1,
            title: 'Clean the bathroom',
            status: 'overdue',
            days_until_due: -3,
            repeats: 'weekly',
            weekdays: [1, 4],
            next_due: '2026-07-15T00:00:00Z',
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Anna', last_name: 'Aardvark' })],
          }),
          makeDueChore({
            id: 2,
            title: 'Do the dishes',
            status: 'today',
            days_until_due: 0,
            repeats: 'daily',
            repeat_interval: 2,
            next_due: '2026-07-18T00:00:00Z',
            assignees: [],
          }),
        ]),
      },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    expect(await screen.findByText('5 of 8 done today')).toBeInTheDocument()
    expect(screen.getByText('3 left')).toBeInTheDocument()
    // A visible heading, matching its Unscheduled twin, so the two chore feeds read as a
    // pair. It used to be sr-only; `not.toHaveClass` is what keeps it from going back.
    const heading = screen.getByRole('heading', { name: 'My Chores' })
    expect(heading).not.toHaveClass('sr-only')
    expect(heading.tagName).toBe('H1')

    const overdue = screen.getByText('Clean the bathroom').closest('li')!
    expect(overdue.querySelector('.bg-due-overdue')).toBeTruthy()
    expect(overdue.textContent).toContain('3 days overdue')
    // The row spells out the whole schedule, not just the period.
    expect(overdue.textContent).toContain('Weekly (Tue, Fri)')
    expect(overdue.textContent).toContain('Anna Aardvark')

    const unassigned = screen.getByText('Do the dishes').closest('li')!
    expect(unassigned.querySelector('.bg-due-today')).toBeTruthy()
    expect(unassigned.textContent).toContain('Every 2 days')
    expect(unassigned.textContent).toContain('Unassigned')
  })

  it('greys the status dot for a chore due more than a week out', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 0, [
          makeDueChore({
            id: 1,
            title: 'Descale the kettle',
            status: 'soon',
            days_until_due: 30,
            next_due: '2026-08-20T00:00:00Z',
          }),
        ]),
      },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    const row = (await screen.findByText('Descale the kettle')).closest('li')!
    expect(row.querySelector('.bg-due-later')).toBeTruthy()
    expect(row.querySelector('.bg-due-soon')).toBeNull()
  })

  it('rules off the three due sections, with no rule above the first', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 0, [
          // next_due agrees with days_until_due, so the rendered order is the
          // one the sections are cut on rather than an id tie-break.
          nextDue(1, 'Bins', -1, '2026-07-17'),
          nextDue(2, 'Dishes', 0, '2026-07-18'),
          nextDue(3, 'Plants', 3, '2026-07-21'),
          nextDue(4, 'Oven', 12, '2026-07-30'),
        ]),
      },
    ])
    const { container } = renderWithProviders(<Home />, {
      authValue: { user: makeUser({ id: 1 }) },
    })

    await screen.findByText('Bins')
    // The rules are aria-hidden, so they are invisible to role queries.
    expect(container.querySelectorAll('li[aria-hidden]')).toHaveLength(2)

    // Position, not just count: a rule opens each later section and nothing
    // sits above the very first row.
    const row = (title: string) => screen.getByText(title).closest('li')!
    expect(row('Bins').previousElementSibling).toBeNull()
    expect(row('Dishes').previousElementSibling).toBe(row('Bins'))
    expect(row('Plants').previousElementSibling).toHaveAttribute('aria-hidden')
    expect(row('Oven').previousElementSibling).toHaveAttribute('aria-hidden')
    // It has to be a rule, not blank space: without the border the sections
    // would still be spaced apart and every other assertion here would pass.
    expect(row('Plants').previousElementSibling).toHaveClass('border-t')
  })

  it('collapses a rule when the section it divides empties out', async () => {
    let homeCalls = 0
    const items = [
      nextDue(1, 'Bins', -1, '2026-07-17'),
      nextDue(2, 'Plants', 2, '2026-07-20'),
      nextDue(3, 'Oven', 12, '2026-07-30'),
    ]
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: () => {
          homeCalls += 1
          return homeCalls === 1 ? homeBody(0, 1, items) : homeBody(1, 1, [items[0], items[2]])
        },
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { container } = renderWithProviders(<Home />, {
      authValue: { user: makeUser({ id: 1 }) },
    })

    const done = await screen.findByRole('button', { name: /^Done: .*Plants/ })
    const rules = () => [...container.querySelectorAll('li[aria-hidden]')]
    expect(rules().map((r) => r.hasAttribute('data-exiting'))).toEqual([false, false])

    // Completing the sole chore due this week empties the middle section, so
    // both rules lose what they divide: the one above it via its own group, the
    // one below it via the preceding group. Each pins a different clause.
    await user.click(done)
    expect(rules().map((r) => r.hasAttribute('data-exiting'))).toEqual([true, true])
  })

  it('leaves the rule alone while its section still has other chores', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 2, [
          nextDue(1, 'Bins', 0, '2026-07-18'),
          nextDue(2, 'Dishes', 0, '2026-07-18'),
          nextDue(3, 'Plants', 2, '2026-07-20'),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { container } = renderWithProviders(<Home />, {
      authValue: { user: makeUser({ id: 1 }) },
    })

    // One of two chores due today: the section survives, so the rule must stay
    // put. This is what makes the guard `every` rather than `some`.
    await user.click(await screen.findByRole('button', { name: /^Done: .*Bins/ }))
    expect(container.querySelector('li[aria-hidden]')).not.toHaveAttribute('data-exiting')
  })

  it('draws no rule when every chore falls in one section', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 0, [
          nextDue(1, 'Plants', 2, '2026-07-20'),
          nextDue(2, 'Bins', 4, '2026-07-22'),
        ]),
      },
    ])
    const { container } = renderWithProviders(<Home />, {
      authValue: { user: makeUser({ id: 1 }) },
    })

    await screen.findByText('Plants')
    expect(container.querySelectorAll('li[aria-hidden]')).toHaveLength(0)
  })

  it('seeds the default query with the current user (your chores + shared)', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      { path: HOME, method: 'GET', body: homeBody(0, 0, []) },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await waitFor(() => expect(homeGets(fetchMock)[0]).toContain('assignee_id=1'))
  })

  it('completes an unassigned chore: posts (no body), refetches, and the row goes', async () => {
    let homeCalls = 0
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: () => {
          homeCalls += 1
          return homeCalls === 1
            ? homeBody(0, 1, [
                makeDueChore({ id: 7, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
              ])
            : homeBody(1, 1, [])
        },
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: /^Done: .*Do the dishes/ }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    const post = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes('/api/v1/chores/7/complete') && init?.method === 'POST',
    )!
    expect(post[1]?.body).toBeUndefined() // credited to the caller
    await waitFor(() => expect(screen.queryByText('Do the dishes')).not.toBeInTheDocument())
    expect(screen.getByText('1 of 1 done today')).toBeInTheDocument()
    expect(homeGets(fetchMock).length).toBe(2) // load + post-completion refetch
  })

  it('refetches after completion and shows a recurring chore at its next occurrence', async () => {
    let homeCalls = 0
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: () => {
          homeCalls += 1
          return homeCalls === 1
            ? homeBody(0, 1, [
                makeDueChore({
                  id: 7,
                  title: 'Do the dishes',
                  repeats: 'daily',
                  status: 'today',
                  days_until_due: 0,
                }),
              ])
            : homeBody(1, 1, [
                makeDueChore({
                  id: 7,
                  title: 'Do the dishes',
                  repeats: 'daily',
                  status: 'soon',
                  days_until_due: 1,
                }),
              ])
        },
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: /^Done: .*Do the dishes/ }))

    await waitFor(() => {
      const row = screen.getByText('Do the dishes').closest('li')!
      expect(row.textContent).toContain('in 1 day')
      expect(row.querySelector('.bg-due-soon')).toBeTruthy()
    })
    expect(screen.getByText('1 of 1 done today')).toBeInTheDocument()
  })

  it('shows the progress returned by the post-completion refetch, not a client guess', async () => {
    let homeCalls = 0
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: () => {
          homeCalls += 1
          return homeCalls === 1
            ? homeBody(1, 2, [
                makeDueChore({
                  id: 5,
                  title: 'Water the plants',
                  status: 'soon',
                  days_until_due: 3,
                }),
                makeDueChore({ id: 6, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
              ])
            : homeBody(2, 3, [
                makeDueChore({ id: 6, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
              ])
        },
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: /^Done: .*Water the plants/ }))

    await waitFor(() => expect(screen.queryByText('Water the plants')).not.toBeInTheDocument())
    expect(screen.getByText('2 of 3 done today')).toBeInTheDocument()
  })

  it('shows an error and keeps the row (no refetch) when completion fails', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 1, [
          makeDueChore({ id: 7, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 500, body: { detail: 'server exploded' } },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: /^Done: .*Do the dishes/ }))

    expect(await screen.findByText('server exploded')).toBeInTheDocument()
    expect(screen.getByText('Do the dishes')).toBeInTheDocument()
    expect(homeGets(fetchMock).length).toBe(1) // a failed completion does not refetch
  })

  it('marks the row exiting and disables the button while it animates out', async () => {
    let homeCalls = 0
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: () => {
          homeCalls += 1
          return homeCalls === 1
            ? homeBody(0, 1, [
                makeDueChore({ id: 7, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
              ])
            : homeBody(1, 1, [])
        },
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    const doneButton = await screen.findByRole('button', { name: /^Done: .*Do the dishes/ })
    const row = doneButton.closest('li')!
    await user.click(doneButton)

    expect(row).toHaveAttribute('data-exiting')
    expect(doneButton).toBeDisabled()
    await waitFor(() => expect(screen.queryByText('Do the dishes')).not.toBeInTheDocument())
  })

  it('shows the empty state when nothing is due', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      { path: HOME, method: 'GET', body: homeBody(0, 0, []) },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    expect(await screen.findByText('All caught up')).toBeInTheDocument()
    expect(screen.queryByText(/done today/)).not.toBeInTheDocument()
  })

  it('shows an error when the due view fails to load', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      { path: HOME, method: 'GET', status: 500, body: { detail: 'boom' } },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    expect(await screen.findByText('Failed to load your due chores')).toBeInTheDocument()
  })

  it('widening the assignee filter sends every selected assignee_id', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: MULTI_OPTIONS },
      { path: HOME, method: 'GET', body: homeBody(0, 0, []) },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: /Bram Bakker/ }))

    await waitFor(() => {
      const last = homeGets(fetchMock).at(-1)!
      expect(last).toContain('assignee_id=1')
      expect(last).toContain('assignee_id=2')
    })
  })

  it('narrows by household, sending household_id on the query', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: MULTI_OPTIONS },
      { path: HOME, method: 'GET', body: homeBody(0, 0, []) },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Flat B' }))

    await waitFor(() => expect(homeGets(fetchMock).at(-1)).toContain('household_id=2'))
  })

  it('opens the credit dialog for another member’s chore and credits the assignee', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 1, [
          makeDueChore({
            id: 10,
            title: 'Water plants',
            status: 'today',
            days_until_due: 0,
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Anna', last_name: 'Aardvark' })],
          }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: /^Done: .*Water plants/ }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText('Complete “Water plants”?')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Done as Anna Aardvark' }))

    const post = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes('/api/v1/chores/10/complete') && init?.method === 'POST',
    )!
    expect(JSON.parse(String(post[1]?.body))).toEqual({ completed_by_user_id: 2 })
  })

  it('credits me when choosing “Done as me” on another member’s chore', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 1, [
          makeDueChore({
            id: 11,
            title: 'Vacuum',
            status: 'today',
            days_until_due: 0,
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Anna', last_name: 'Aardvark' })],
          }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: /^Done: .*Vacuum/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Done as me' }))

    const post = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes('/api/v1/chores/11/complete') && init?.method === 'POST',
    )!
    expect(post[1]?.body).toBeUndefined()
  })

  it('labels each card with its household when the user spans multiple households', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: MULTI_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 1, [
          makeDueChore({
            id: 1,
            title: 'Clean the bathroom',
            household: { id: 2, name: 'Flat B' },
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Anna', last_name: 'Aardvark' })],
          }),
        ]),
      },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    // The assignee renders twice (mobile stacked line + desktop right column),
    // so assert on the count rather than a single node.
    const row = (await screen.findByText('Clean the bathroom')).closest('li')!
    expect(within(row).getAllByText('Flat B').length).toBeGreaterThan(0)
    expect(within(row).getAllByText('Anna Aardvark').length).toBeGreaterThan(0)
  })

  it('omits the household label for a single-household user but keeps the assignee', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET',
        body: homeBody(0, 1, [
          makeDueChore({
            id: 1,
            title: 'Clean the bathroom',
            household: { id: 1, name: 'Test Household' },
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Anna', last_name: 'Aardvark' })],
          }),
        ]),
      },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    const row = (await screen.findByText('Clean the bathroom')).closest('li')!
    expect(within(row).getAllByText('Anna Aardvark').length).toBeGreaterThan(0)
    expect(within(row).queryByText('Test Household')).not.toBeInTheDocument()
  })
})

describe('description dialog', () => {
  const CHORE_12 = '/api/v1/chores/12'

  function routes(has: boolean) {
    return [
      { path: FILTERS, method: 'GET' as const, body: SOLO_OPTIONS },
      {
        path: HOME,
        method: 'GET' as const,
        body: homeBody(0, 1, [makeDueChore({ id: 12, title: 'Bathroom', has_description: has })]),
      },
    ]
  }

  it('offers no marker for a chore with no instructions', async () => {
    mockFetch(routes(false))
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    // Waits for the row first: asserting absence before the list lands would pass on an empty
    // page and prove nothing.
    expect(await screen.findByRole('button', { name: 'Done: “Bathroom”' })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Description: “Bathroom”' }),
    ).not.toBeInTheDocument()
  })

  it('fetches the instructions on open and renders them as HTML', async () => {
    const fetchMock = mockFetch([
      ...routes(true),
      {
        path: CHORE_12,
        method: 'GET',
        body: makeChore({
          id: 12,
          title: 'Bathroom',
          description: '<p>Scrub the tub, then:</p><ul><li>replace the towels</li></ul>',
        }),
      },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    // Not requested with the list: the payload carries only the flag, which is the whole reason
    // the dialog fetches at all.
    expect(
      await screen.findByRole('button', { name: 'Description: “Bathroom”' }),
    ).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === CHORE_12)).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Description: “Bathroom”' }))
    const dialog = within(await screen.findByRole('dialog'))
    expect(dialog.getByRole('heading', { name: 'Bathroom' })).toBeInTheDocument()
    expect(await dialog.findByText('replace the towels')).toBeInTheDocument()
    expect(dialog.getByText('replace the towels').tagName).toBe('LI')
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === CHORE_12)).toHaveLength(1)
  })

  it('refetches on a second open rather than caching', async () => {
    // Deliberately uncached: a description can be edited between two opens, and one request is
    // cheaper than reasoning about when to invalidate.
    let n = 0
    const fetchMock = mockFetch([
      ...routes(true),
      {
        path: CHORE_12,
        method: 'GET',
        body: () => {
          n += 1
          return makeChore({ id: 12, title: 'Bathroom', description: `<p>version ${n}</p>` })
        },
      },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: 'Description: “Bathroom”' }))
    expect(
      await within(await screen.findByRole('dialog')).findByText('version 1'),
    ).toBeInTheDocument()
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Description: “Bathroom”' }))
    expect(
      await within(await screen.findByRole('dialog')).findByText('version 2'),
    ).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === CHORE_12)).toHaveLength(2)
  })
  describe('skipping a chore', () => {
    const CHORE = () =>
      makeDueChore({ id: 7, title: 'Do the dishes', status: 'today', days_until_due: 0 })

    function stub(skipResponse: { status: number; body: unknown }) {
      let homeCalls = 0
      return mockFetch([
        { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
        {
          path: HOME,
          method: 'GET',
          body: () => {
            homeCalls += 1
            return homeCalls === 1 ? homeBody(0, 1, [CHORE()]) : homeBody(1, 1, [])
          },
        },
        { path: SKIP, method: 'POST', ...skipResponse },
      ])
    }

    it('confirms first, then posts (no body) and refetches', async () => {
      const fetchMock = stub({ status: 201, body: {} })
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

      await user.click(await screen.findByRole('button', { name: /^Skip: .*Do the dishes/ }))

      // Nothing is sent until the confirmation is accepted: unlike Done, a skip moves the
      // chore's schedule on, so undoing a mis-click means going and finding it on History.
      const dialog = await screen.findByRole('alertdialog')
      expect(within(dialog).getByText('Skip “Do the dishes”?')).toBeInTheDocument()
      expect(fetchMock.mock.calls.some(([url]) => SKIP.test(String(url)))).toBe(false)

      await user.click(within(dialog).getByRole('button', { name: 'Skip it' }))

      const post = await waitFor(() =>
        fetchMock.mock.calls.find(
          ([url, init]) => String(url).includes('/api/v1/chores/7/skip') && init?.method === 'POST',
        )!,
      )
      expect(post[1]?.body).toBeUndefined() // no credit to assign, so no body
      await waitFor(() => expect(screen.queryByText('Do the dishes')).not.toBeInTheDocument())
      expect(homeGets(fetchMock).length).toBe(2) // load + post-skip refetch
    })

    it('sends nothing when the confirmation is cancelled', async () => {
      const fetchMock = stub({ status: 201, body: {} })
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

      await user.click(await screen.findByRole('button', { name: /^Skip: .*Do the dishes/ }))
      const dialog = await screen.findByRole('alertdialog')
      await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

      expect(fetchMock.mock.calls.some(([url]) => SKIP.test(String(url)))).toBe(false)
      expect(screen.getByText('Do the dishes')).toBeInTheDocument()
      expect(homeGets(fetchMock).length).toBe(1)
    })

    it('shows the error and keeps the row (no refetch) when the skip fails', async () => {
      const fetchMock = stub({ status: 400, body: { detail: 'nothing to skip' } })
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

      await user.click(await screen.findByRole('button', { name: /^Skip: .*Do the dishes/ }))
      const dialog = await screen.findByRole('alertdialog')
      await user.click(within(dialog).getByRole('button', { name: 'Skip it' }))

      expect(await screen.findByText('nothing to skip')).toBeInTheDocument()
      expect(screen.getByText('Do the dishes')).toBeInTheDocument()
      expect(homeGets(fetchMock).length).toBe(1)
    })

    it('disables both row actions while the row animates out', async () => {
      stub({ status: 201, body: {} })
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

      const skipButton = await screen.findByRole('button', { name: /^Skip: .*Do the dishes/ })
      const doneButton = screen.getByRole('button', { name: /^Done: .*Do the dishes/ })
      const row = skipButton.closest('li')!
      await user.click(skipButton)
      await user.click(
        within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Skip it' }),
      )

      expect(row).toHaveAttribute('data-exiting')
      expect(skipButton).toBeDisabled()
      expect(doneButton).toBeDisabled()
      await waitFor(() => expect(screen.queryByText('Do the dishes')).not.toBeInTheDocument())
    })
  })
})
