import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import Unscheduled from './Unscheduled'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeHouseholdMember, makeUnscheduledChore, makeUser } from '../test/fixtures'
import type { HistoryFilterOptions, UnscheduledChore } from '../lib/types'

const LIST = /\/api\/v1\/unscheduled/
const COMPLETE = /\/api\/v1\/chores\/\d+\/complete/
const FILTERS = '/api/v1/completions/filters'

// One household, one member: the filter bar has nothing to offer and stays hidden.
const SOLO_OPTIONS: HistoryFilterOptions = {
  households: [{ id: 1, name: 'Flat' }],
  members: [makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' })],
}

const MULTI_OPTIONS: HistoryFilterOptions = {
  households: [
    { id: 1, name: 'Flat' },
    { id: 2, name: 'Cottage' },
  ],
  members: [
    makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
    makeHouseholdMember({ id: 2, first_name: 'Bram', last_name: 'Bakker' }),
  ],
}

function body(items: UnscheduledChore[]) {
  return { items }
}

// The GET urls the page issued, so a test can assert what the filters sent.
function listGets(fetchMock: ReturnType<typeof mockFetch>): string[] {
  return fetchMock.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.includes('/api/v1/unscheduled'))
}

describe('Unscheduled', () => {
  it('renders a heading, and each row with its recency label and dot', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: LIST,
        method: 'GET',
        body: body([
          makeUnscheduledChore({
            id: 1,
            title: 'Deep clean the oven',
            days_since_last_completion: 0,
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Anna', last_name: 'Aardvark' })],
          }),
          makeUnscheduledChore({
            id: 2,
            title: 'Descale the kettle',
            days_since_last_completion: 4,
            assignees: [],
          }),
          makeUnscheduledChore({
            id: 3,
            title: 'Sort the loft',
            days_since_last_completion: null,
            assignees: [],
          }),
        ]),
      },
    ])
    renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })

    // Unlike Your Chores this page keeps a heading, so the two are distinguishable even
    // when both filter bars are hidden.
    expect(screen.getByRole('heading', { name: 'Unscheduled Chores' })).toBeInTheDocument()

    const today = (await screen.findByText('Deep clean the oven')).closest('li')!
    expect(today.querySelector('.bg-done-recent')).toBeTruthy()
    expect(today.textContent).toContain('Last done today')
    expect(today.textContent).toContain('Anna Aardvark')

    const week = screen.getByText('Descale the kettle').closest('li')!
    expect(week.querySelector('.bg-done-week')).toBeTruthy()
    expect(week.textContent).toContain('Last done 4 days ago')
    expect(week.textContent).toContain('Unassigned')

    const never = screen.getByText('Sort the loft').closest('li')!
    expect(never.querySelector('.bg-done-stale')).toBeTruthy()
    expect(never.textContent).toContain('Never done')
  })

  it('shows no due date, repeat label or progress card', async () => {
    // Nothing here is due, so the page must not borrow the due view's furniture: no
    // "in N days"/"overdue" copy, no "Unscheduled" repeat label (every row is), and no
    // done-today progress bar.
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      { path: LIST, method: 'GET', body: body([makeUnscheduledChore({ title: 'Kettle' })]) },
    ])
    renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })

    const row = (await screen.findByText('Kettle')).closest('li')!
    expect(row.textContent).not.toMatch(/overdue|Due today|in \d+ day/)
    expect(row.textContent).not.toContain('Unscheduled')
    // Anchored on the progress card's own wording ("N of M done today"): a bare
    // /done today/ would also match a row's "Last done today" label and pass by accident.
    expect(screen.queryByText(/of \d+ done today/)).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('draws no section rules, however the recency buckets fall', async () => {
    // The due view divides its list into three sections; this one is flat, so a row's
    // recency must never introduce a separator.
    const { container } = renderUnscheduled([
      makeUnscheduledChore({ id: 1, title: 'A', days_since_last_completion: 0 }),
      makeUnscheduledChore({ id: 2, title: 'B', days_since_last_completion: 4 }),
      makeUnscheduledChore({ id: 3, title: 'C', days_since_last_completion: null }),
    ])

    await screen.findByText('A')
    expect(container.querySelectorAll('li[aria-hidden]')).toHaveLength(0)
  })

  it('keeps the row after completing it, and refetches', async () => {
    let calls = 0
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: LIST,
        method: 'GET',
        // Second read: the chore is still listed, now done today.
        body: () => {
          calls += 1
          return body([
            makeUnscheduledChore({
              id: 7,
              title: 'Kettle',
              days_since_last_completion: calls === 1 ? 12 : 0,
            }),
          ])
        },
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const success = vi.spyOn(toast, 'success')
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })

    expect(await screen.findByText('Last done 12 days ago')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Done: “Kettle”' }))

    // Still there, with its clock reset: an unscheduled chore is repeatable, so completing
    // it must not remove the row the way the due view does.
    expect(await screen.findByText('Last done today')).toBeInTheDocument()
    expect(screen.getByText('Kettle')).toBeInTheDocument()
    await waitFor(() => expect(listGets(fetchMock)).toHaveLength(2))
    // The row stays put, so the toast is what confirms the completion happened.
    expect(success).toHaveBeenCalledWith('Chore marked done')
  })

  it('credits the caller by default, sending no body', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      {
        path: LIST,
        method: 'GET',
        body: body([
          makeUnscheduledChore({
            id: 7,
            title: 'Kettle',
            assignees: [makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' })],
          }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: 'Done: “Kettle”' }))

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(post[1]?.body).toBeUndefined()
  })

  it('asks who to credit for a chore assigned only to someone else', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: MULTI_OPTIONS },
      {
        path: LIST,
        method: 'GET',
        body: body([
          makeUnscheduledChore({
            id: 7,
            title: 'Kettle',
            assignees: [makeHouseholdMember({ id: 2, first_name: 'Bram', last_name: 'Bakker' })],
          }),
        ]),
      },
      { path: COMPLETE, method: 'POST', status: 201, body: {} },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })

    await user.click(await screen.findByRole('button', { name: 'Done: “Kettle”' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Done as Bram Bakker' }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
      expect(JSON.parse(String(post[1]?.body))).toEqual({ completed_by_user_id: 2 })
    })
  })

  it('hides the filters for a lone user in a lone household', async () => {
    renderUnscheduled([makeUnscheduledChore()], SOLO_OPTIONS)

    await screen.findByText('Descale the kettle')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Assignees' })).not.toBeInTheDocument()
  })

  it('narrows by household and by assignee through the query string', async () => {
    const fetchMock = mockFetch([
      { path: FILTERS, method: 'GET', body: MULTI_OPTIONS },
      { path: LIST, method: 'GET', body: body([]) },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })

    // Seeded with the current user, like the due view.
    await waitFor(() => expect(listGets(fetchMock).at(-1)).toContain('assignee_id=1'))

    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Cottage' }))

    await waitFor(() => expect(listGets(fetchMock).at(-1)).toContain('household_id=2'))
  })

  it('shows an empty state when nothing is waiting', async () => {
    renderUnscheduled([])

    expect(await screen.findByText('Nothing waiting')).toBeInTheDocument()
    expect(screen.getByText('Chores with no schedule show up here.')).toBeInTheDocument()
  })

  it('reports a load failure inline', async () => {
    mockFetch([
      { path: FILTERS, method: 'GET', body: SOLO_OPTIONS },
      { path: LIST, method: 'GET', status: 500, body: { detail: 'boom' } },
    ])
    renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })

    expect(await screen.findByText('Failed to load your unscheduled chores')).toBeInTheDocument()
  })
})

// Shared setup for the tests that only care about what is rendered.
function renderUnscheduled(items: UnscheduledChore[], options = SOLO_OPTIONS) {
  mockFetch([
    { path: FILTERS, method: 'GET', body: options },
    { path: LIST, method: 'GET', body: body(items) },
  ])
  return renderWithProviders(<Unscheduled />, { authValue: { user: makeUser({ id: 1 }) } })
}
