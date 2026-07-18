import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import History from './History'
import { renderWithProviders } from '../test/utils'
import { makeHistoryEntry, makeHouseholdMember } from '../test/fixtures'
import type { HistoryEntry, HistoryFilterOptions } from '../lib/types'

const me = makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' })

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
    households: [{ id: 1, name: 'Test Household' }],
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
          household: { id: 4, name: 'Beach House' },
          completed_by: makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
        }),
      ],
    })
    renderWithProviders(<History />)

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    expect(within(row).getByText('Beach House')).toBeInTheDocument()
    expect(within(row).getByText('Jo Ng')).toBeInTheDocument()
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

  it('shows a placeholder when the completer is unknown', async () => {
    stubFetch({ entries: [makeHistoryEntry({ title: 'Orphaned', completed_by: null })] })
    renderWithProviders(<History />)

    const row = (await screen.findByText('Orphaned')).closest('tr')!
    expect(within(row).getByText('Unknown')).toBeInTheDocument()
  })

  it('shows an empty state when there is no history', async () => {
    stubFetch({ entries: [] })
    renderWithProviders(<History />)

    expect(await screen.findByText('No completed chores yet.')).toBeInTheDocument()
  })

  it('filters by person and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      entries: [makeHistoryEntry({ id: 7, title: 'Scrub the tub' })],
      options: {
        households: [{ id: 1, name: 'Test Household' }],
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
          { id: 1, name: 'Flat 3B' },
          { id: 2, name: 'Beach House' },
        ],
        members: [me],
      },
    })
    renderWithProviders(<History />)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Scrub the tub')
    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))

    await waitFor(() => expect(lastCompletionsGet(fetchMock)).toContain('household_id=2'))
  })

  it('hides the person filter when there is a single member', async () => {
    stubFetch({
      entries: [makeHistoryEntry({ title: 'Scrub the tub' })],
      options: { households: [{ id: 1, name: 'Flat 3B' }], members: [me] },
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
})
