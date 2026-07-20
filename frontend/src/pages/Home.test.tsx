import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Home from './Home'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeDueChore, makeUser } from '../test/fixtures'
import type { DueChore } from '../lib/types'

const COMPLETE = /\/api\/v1\/chores\/\d+\/complete/

function homeBody(done: number, total: number, items: DueChore[]) {
  return { progress: { done_today: done, total_today: total }, items }
}

describe('Home', () => {
  it('renders the greeting, progress, and status-coded due rows', async () => {
    mockFetch([
      {
        path: '/api/v1/home',
        method: 'GET',
        body: homeBody(5, 8, [
          makeDueChore({
            id: 1,
            title: 'Clean the bathroom',
            status: 'overdue',
            days_until_due: -3,
            repeats: 'weekly',
            next_due: '2026-07-15T00:00:00Z',
          }),
          makeDueChore({
            id: 2,
            title: 'Do the dishes',
            status: 'today',
            days_until_due: 0,
            repeats: 'daily',
            next_due: '2026-07-18T00:00:00Z',
          }),
          makeDueChore({
            id: 3,
            title: 'Water the plants',
            status: 'soon',
            days_until_due: 2,
            repeats: 'monthly',
            next_due: '2026-07-20T00:00:00Z',
          }),
        ]),
      },
    ])
    renderWithProviders(<Home />, {
      authValue: { user: makeUser({ first_name: 'Alex', last_name: 'Kim' }) },
    })

    expect(screen.getByText('Hi, Alex')).toBeInTheDocument()
    expect(await screen.findByText('5 of 8 done today')).toBeInTheDocument()
    expect(screen.getByText('3 left')).toBeInTheDocument()

    const overdue = screen.getByText('Clean the bathroom').closest('li')!
    expect(overdue.querySelector('.bg-due-overdue')).toBeTruthy()
    expect(overdue.textContent).toContain('3 days overdue')
    expect(overdue.textContent).toContain('Weekly')

    const today = screen.getByText('Do the dishes').closest('li')!
    expect(today.querySelector('.bg-due-today')).toBeTruthy()
    expect(today.textContent).toContain('Due today')

    const soon = screen.getByText('Water the plants').closest('li')!
    expect(soon.querySelector('.bg-due-soon')).toBeTruthy()
    expect(soon.textContent).toContain('in 2 days')
  })

  it('completes a chore: posts, refetches, and the finished one-off disappears', async () => {
    let homeCalls = 0
    const fetchMock = mockFetch([
      {
        path: '/api/v1/home',
        method: 'GET',
        // Load lists the chore; the post-completion refetch no longer does (a
        // completed one-off has no next occurrence).
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
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    const doneButton = await screen.findByRole('button', { name: /Do the dishes/ })
    await user.click(doneButton)

    // The POST fires immediately on click.
    const posted = fetchMock.mock.calls.some(
      ([url, init]) => String(url).includes('/api/v1/chores/7/complete') && init?.method === 'POST',
    )
    expect(posted).toBe(true)
    // The row plays its exit animation, then the refetched list drops it.
    await waitFor(() => expect(screen.queryByText('Do the dishes')).not.toBeInTheDocument())
    expect(screen.getByText('1 of 1 done today')).toBeInTheDocument()
    // Completion triggers a second GET /api/v1/home (the refetch).
    const homeGets = fetchMock.mock.calls.filter(
      ([url, init]) => String(url).includes('/api/v1/home') && (init?.method ?? 'GET') === 'GET',
    )
    expect(homeGets.length).toBe(2)
  })

  it('refetches after completion and shows a recurring chore at its next occurrence', async () => {
    let homeCalls = 0
    mockFetch([
      {
        path: '/api/v1/home',
        method: 'GET',
        // After completing today's occurrence the daily chore is due tomorrow, so
        // the refetch lists it again as a "soon" row (matching a page reload).
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
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    const doneButton = await screen.findByRole('button', { name: /Do the dishes/ })
    await user.click(doneButton)

    // The chore reappears as tomorrow's occurrence once the refetch lands.
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
      {
        path: '/api/v1/home',
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
            : // Server truth after completion (e.g. a housemate also finished one).
              homeBody(2, 3, [
                makeDueChore({ id: 6, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
              ])
        },
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    const doneButton = await screen.findByRole('button', { name: /Water the plants/ })
    await user.click(doneButton)

    await waitFor(() => expect(screen.queryByText('Water the plants')).not.toBeInTheDocument())
    // Progress mirrors the refetch, not any optimistic client bump.
    expect(screen.getByText('2 of 3 done today')).toBeInTheDocument()
  })

  it('shows an error and keeps the row (no refetch) when completion fails', async () => {
    const fetchMock = mockFetch([
      {
        path: '/api/v1/home',
        method: 'GET',
        body: homeBody(0, 1, [
          makeDueChore({ id: 7, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 500, body: { detail: 'server exploded' } },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    const doneButton = await screen.findByRole('button', { name: /Do the dishes/ })
    await user.click(doneButton)

    expect(await screen.findByText('server exploded')).toBeInTheDocument()
    expect(screen.getByText('Do the dishes')).toBeInTheDocument() // row un-collapses in place
    // A failed completion does not refetch.
    const homeGets = fetchMock.mock.calls.filter(
      ([url, init]) => String(url).includes('/api/v1/home') && (init?.method ?? 'GET') === 'GET',
    )
    expect(homeGets.length).toBe(1)
  })

  it('marks the row exiting and disables the button while it animates out', async () => {
    let homeCalls = 0
    mockFetch([
      {
        path: '/api/v1/home',
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
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    const doneButton = await screen.findByRole('button', { name: /Do the dishes/ })
    const row = doneButton.closest('li')!
    await user.click(doneButton)

    // The row is flagged exiting (which drives the CSS animation) and its button
    // is disabled so it can't be double-completed mid-animation.
    expect(row).toHaveAttribute('data-exiting')
    expect(doneButton).toBeDisabled()
    // ...then it's gone once the animation finishes and the refetch lands.
    await waitFor(() => expect(screen.queryByText('Do the dishes')).not.toBeInTheDocument())
  })

  it('shows the empty state when nothing is due', async () => {
    mockFetch([{ path: '/api/v1/home', method: 'GET', body: homeBody(0, 0, []) }])
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    expect(await screen.findByText('All caught up')).toBeInTheDocument()
    expect(screen.queryByText(/done today/)).not.toBeInTheDocument() // no progress card
  })

  it('shows an error when the due view fails to load', async () => {
    mockFetch([{ path: '/api/v1/home', method: 'GET', status: 500, body: { detail: 'boom' } }])
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    expect(await screen.findByText('Failed to load your due chores')).toBeInTheDocument()
  })
})
