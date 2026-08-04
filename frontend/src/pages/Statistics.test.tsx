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
        kpis: {
          completed_in_range: 0,
          skipped_in_range: 0,
          currently_overdue: 0,
          on_time_rate: null,
          active_chores: 0,
        },
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

    expect(await screen.findByText('On time, late or skipped')).toBeInTheDocument()
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
        kpis: {
          completed_in_range: 0,
          skipped_in_range: 0,
          currently_overdue: 0,
          on_time_rate: null,
          active_chores: 0,
        },
        completions_over_time: [],
        status_breakdown: { overdue: 0, today: 0, soon: 0 },
        punctuality: { on_time: 0, late: 0, early: 0, skipped: 0 },
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

  it('offers only the households the user is at least a deputy in', async () => {
    // Same narrowing as History, and for the same reason: /completions/filters is shared with
    // Home and Unscheduled so it cannot be role-scoped server-side, and /stats already excludes
    // helper households, so offering one here would be a filter that returns nothing.
    const fetchMock = stubFetch({
      options: {
        households: [
          { id: 1, name: 'Flat 3B' },
          { id: 2, name: 'Beach House' },
        ],
        members: [makeHouseholdMember()],
      },
    })
    renderWithProviders(<Statistics />, {
      authValue: {
        memberships: [
          { household_id: 1, role: 'deputy', owned: false },
          { household_id: 2, role: 'helper', owned: false },
        ],
      },
    })

    await screen.findByRole('heading', { name: 'Statistics' })
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    // The positive half: the options really loaded, so the missing Select is the narrowing
    // rather than a fixture that never answered.
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/completions/filters'))).toBe(
      true,
    )
  })
  it('carries the skip count in the Completed tile hint', async () => {
    stubFetch({})
    renderWithProviders(<Statistics />)

    // makeStats: 12 completed, 4 skipped, 30d range.
    expect(await screen.findByText('in the last 30 days · 4 skipped')).toBeInTheDocument()
  })

  it('keeps the plain hint when nothing was skipped', async () => {
    stubFetch({ stats: makeStats({ kpis: { ...makeStats().kpis, skipped_in_range: 0 } }) })
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('in the last 30 days')).toBeInTheDocument()
  })

  it('gives skipped chores a slice of the punctuality donut', async () => {
    stubFetch({})
    renderWithProviders(<Statistics />)

    expect(await screen.findByText('On time, late or skipped')).toBeInTheDocument()
    const skippedItem = (await screen.findByText('Skipped')).closest('li')!
    expect(within(skippedItem).getByText('4')).toBeInTheDocument()
  })

  it('draws the time chart for a range that holds nothing but skips', async () => {
    stubFetch({
      stats: makeStats({
        kpis: { ...makeStats().kpis, completed_in_range: 0, skipped_in_range: 3 },
        completions_over_time: [
          { bucket: '2026-07-01', count: 0, skipped: 1 },
          { bucket: '2026-07-02', count: 0, skipped: 2 },
        ],
      }),
    })
    renderWithProviders(<Statistics />)

    // The chart's own empty state counts both series, so a skips-only range still plots
    // rather than claiming there is no data.
    expect(await screen.findByText('Completions over time')).toBeInTheDocument()
    const chartCard = screen
      .getByText('Completions over time')
      .closest<HTMLElement>('div.rounded-xl')!
    expect(within(chartCard).queryByText('Not enough data yet.')).not.toBeInTheDocument()
  })
})
