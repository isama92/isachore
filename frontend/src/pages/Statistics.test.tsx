import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Statistics from './Statistics'
import { renderWithProviders } from '../test/utils'
import { makeHouseholdMember, makeStats } from '../test/fixtures'
import type { HistoryFilterOptions, StatsData } from '../lib/types'

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
  stats?: StatsData
  options?: HistoryFilterOptions
  statsStatus?: number
}): FetchMock {
  const options = opts.options ?? {
    households: [{ id: 1, name: 'Test Household' }],
    members: [makeHouseholdMember()],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/completions/filters')) {
      return jsonBody(options)
    }
    if (method === 'GET' && path.endsWith('/api/v1/stats')) {
      return jsonBody(opts.stats ?? makeStats(), opts.statsStatus ?? 200)
    }
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastStatsGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(
    ([url, init]) =>
      (init?.method ?? 'GET').toUpperCase() === 'GET' &&
      String(url).split('?')[0].endsWith('/api/v1/stats'),
  )
  return String(calls.at(-1)?.[0] ?? '')
}

describe('Statistics', () => {
  it('shows the KPI tiles from the stats payload', async () => {
    stubFetch({})
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('12')).toBeInTheDocument() // completed_in_range
    expect(screen.getByText('On-time rate')).toBeInTheDocument()
    expect(screen.getByText('80%')).toBeInTheDocument() // on_time_rate 0.8
    expect(screen.getByText('Overdue now')).toBeInTheDocument()
    expect(screen.getByText('Active chores')).toBeInTheDocument()
  })

  it('renders a dash for the on-time rate when nothing was completed', async () => {
    stubFetch({
      stats: makeStats({
        kpis: { completed_in_range: 0, currently_overdue: 0, on_time_rate: null, active_chores: 0 },
      }),
    })
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('—')).toBeInTheDocument()
  })

  it('renders the status donut legend with labels and counts', async () => {
    stubFetch({})
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('Current status')).toBeInTheDocument()
    const todayItem = (await screen.findByText('Due today')).closest('li')!
    expect(within(todayItem).getByText('1')).toBeInTheDocument()
    const soonItem = screen.getByText('Upcoming').closest('li')!
    expect(within(soonItem).getByText('2')).toBeInTheDocument()
  })

  it('renders the punctuality donut legend', async () => {
    stubFetch({})
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('On time vs late')).toBeInTheDocument()
    const lateItem = (await screen.findByText('Late')).closest('li')!
    expect(within(lateItem).getByText('3')).toBeInTheDocument()
  })

  it('lists completions per person, ranked, with counts', async () => {
    stubFetch({})
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('Completions per person')).toBeInTheDocument()
    const avaRow = (await screen.findByText('Ava One')).closest('li')!
    expect(within(avaRow).getByText('7')).toBeInTheDocument()
    const benRow = screen.getByText('Ben Two').closest('li')!
    expect(within(benRow).getByText('5')).toBeInTheDocument()
  })

  it('shows empty messages when there is no data in range', async () => {
    stubFetch({
      stats: makeStats({
        kpis: { completed_in_range: 0, currently_overdue: 0, on_time_rate: null, active_chores: 0 },
        completions_over_time: [],
        status_breakdown: { overdue: 0, today: 0, soon: 0 },
        punctuality: { on_time: 0, late: 0, early: 0 },
        per_person: [],
      }),
    })
    renderWithProviders(<Statistics />)

    // The time chart, both donuts and the per-person list each fall back to the
    // empty message.
    const empties = await screen.findAllByText('Not enough data yet.')
    expect(empties.length).toBeGreaterThanOrEqual(3)
  })

  it('defaults to the 30-day range and refetches when the range changes', async () => {
    const fetchMock = stubFetch({})
    renderWithProviders(<Statistics />)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('80%')
    expect(lastStatsGet(fetchMock)).toContain('range=30d')

    await user.click(screen.getByText('7 days'))
    await waitFor(() => expect(lastStatsGet(fetchMock)).toContain('range=7d'))
  })

  it('filters by person and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      options: {
        households: [{ id: 1, name: 'Test Household' }],
        members: [
          makeHouseholdMember({ id: 1, first_name: 'Me', last_name: 'Here' }),
          makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
        ],
      },
    })
    renderWithProviders(<Statistics />)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('80%')
    await user.click(await screen.findByRole('combobox', { name: 'Person' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))

    await waitFor(() => expect(lastStatsGet(fetchMock)).toContain('user_id=2'))
  })

  it('hides the filters when there is a single member and household', async () => {
    stubFetch({
      options: { households: [{ id: 1, name: 'Flat 3B' }], members: [makeHouseholdMember()] },
    })
    renderWithProviders(<Statistics />)

    await screen.findByText('80%')
    expect(screen.queryByRole('combobox', { name: 'Person' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('shows an error when loading fails', async () => {
    stubFetch({ statsStatus: 500 })
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('Failed to load statistics')).toBeInTheDocument()
  })
})
