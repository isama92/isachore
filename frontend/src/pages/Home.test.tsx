import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Home from './Home'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeDueChore, makeHouseholdMember, makeUser } from '../test/fixtures'
import type { DueChore, HistoryFilterOptions } from '../lib/types'

const HOME = /\/api\/v1\/home/
const FILTERS = '/api/v1/completions/filters'
const COMPLETE = /\/api\/v1\/chores\/\d+\/complete/

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

function homeGets(fetchMock: ReturnType<typeof mockFetch>): string[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => HOME.test(String(url)) && (init?.method ?? 'GET') === 'GET')
    .map(([url]) => String(url))
}

describe('Home', () => {
  it('renders the personal heading, progress, and status-coded due rows', async () => {
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
            next_due: '2026-07-15T00:00:00Z',
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Anna', last_name: 'Aardvark' })],
          }),
          makeDueChore({
            id: 2,
            title: 'Do the dishes',
            status: 'today',
            days_until_due: 0,
            repeats: 'daily',
            next_due: '2026-07-18T00:00:00Z',
            assignees: [],
          }),
        ]),
      },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    // Default (assignee filter = me) -> personal heading.
    expect(screen.getByText('Your chores')).toBeInTheDocument()
    expect(await screen.findByText('5 of 8 done today')).toBeInTheDocument()
    expect(screen.getByText('3 left')).toBeInTheDocument()

    const overdue = screen.getByText('Clean the bathroom').closest('li')!
    expect(overdue.querySelector('.bg-due-overdue')).toBeTruthy()
    expect(overdue.textContent).toContain('3 days overdue')
    expect(overdue.textContent).toContain('Weekly')
    expect(overdue.textContent).toContain('Anna Aardvark')

    const unassigned = screen.getByText('Do the dishes').closest('li')!
    expect(unassigned.querySelector('.bg-due-today')).toBeTruthy()
    expect(unassigned.textContent).toContain('Unassigned')
  })

  it('seeds the default query with the current user (your chores + shared)', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      { path: HOME, method: 'GET', body: homeBody(0, 0, []) },
    ])
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    await waitFor(() => expect(homeGets(fetchMock)[0]).toContain('assignee_id=1'))
  })

  it('completes an unassigned chore: posts (no body), refetches, and the one-off disappears', async () => {
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

    await user.click(await screen.findByRole('button', { name: /Do the dishes/ }))

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

    await user.click(await screen.findByRole('button', { name: /Do the dishes/ }))

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

    await user.click(await screen.findByRole('button', { name: /Water the plants/ }))

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

    await user.click(await screen.findByRole('button', { name: /Do the dishes/ }))

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

    const doneButton = await screen.findByRole('button', { name: /Do the dishes/ })
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

  it('widening the assignee filter switches the heading and sends assignee_id', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: MULTI_OPTIONS },
      { path: HOME, method: 'GET', body: homeBody(0, 0, []) },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser({ id: 1 }) } })

    expect(await screen.findByText('Your chores')).toBeInTheDocument()

    await user.click(await screen.findByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: /Bram Bakker/ }))

    expect(await screen.findByText('Household chores')).toBeInTheDocument()
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

    await user.click(await screen.findByRole('button', { name: /Water plants/ }))
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

    await user.click(await screen.findByRole('button', { name: /Vacuum/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Done as me' }))

    const post = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes('/api/v1/chores/11/complete') && init?.method === 'POST',
    )!
    expect(post[1]?.body).toBeUndefined()
  })
})
