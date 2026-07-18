import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
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

    expect(screen.getByText('Hi Alex Kim')).toBeInTheDocument()
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

  it('completes a chore: posts, removes the row, and advances progress', async () => {
    const fetchMock = mockFetch([
      {
        path: '/api/v1/home',
        method: 'GET',
        body: homeBody(0, 1, [
          makeDueChore({ id: 7, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    const checkbox = await screen.findByRole('checkbox', { name: /Do the dishes/ })
    await user.click(checkbox)

    // Optimistic: the row is removed immediately on check.
    expect(screen.queryByText('Do the dishes')).not.toBeInTheDocument()
    const posted = fetchMock.mock.calls.some(
      ([url, init]) => String(url).includes('/api/v1/chores/7/complete') && init?.method === 'POST',
    )
    expect(posted).toBe(true)
    // A due-today task is now done: progress moves to 1 of 1.
    expect(screen.getByText('1 of 1 done today')).toBeInTheDocument()
  })

  it('completing a not-yet-due chore removes it without advancing progress', async () => {
    mockFetch([
      {
        path: '/api/v1/home',
        method: 'GET',
        body: homeBody(1, 2, [
          makeDueChore({ id: 5, title: 'Water the plants', status: 'soon', days_until_due: 3 }),
          makeDueChore({ id: 6, title: 'Do the dishes', status: 'today', days_until_due: 0 }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Home />, { authValue: { user: makeUser() } })

    const checkbox = await screen.findByRole('checkbox', { name: /Water the plants/ })
    await user.click(checkbox)

    expect(screen.queryByText('Water the plants')).not.toBeInTheDocument()
    // A future ("soon") occurrence doesn't count toward today, so progress holds.
    expect(screen.getByText('1 of 2 done today')).toBeInTheDocument()
  })

  it('restores the row and shows an error when completion fails', async () => {
    mockFetch([
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

    const checkbox = await screen.findByRole('checkbox', { name: /Do the dishes/ })
    await user.click(checkbox)

    expect(await screen.findByText('server exploded')).toBeInTheDocument()
    expect(screen.getByText('Do the dishes')).toBeInTheDocument() // rolled back
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
