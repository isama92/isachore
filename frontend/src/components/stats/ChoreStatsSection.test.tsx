import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChoreStatsSection from './ChoreStatsSection'
import { mockFetch, renderWithProviders } from '../../test/utils'
import type { ChoreStatsData, StatsChoreOption, StatsRange } from '../../lib/types'

const OPTIONS = /\/api\/v1\/stats\/chores(\?.*)?$/
const DETAIL = /\/api\/v1\/stats\/chores\/\d+\?/

const BINS: StatsChoreOption = { id: 4, title: 'Bins', household_id: 1, household_name: 'Flat' }
const DISHES: StatsChoreOption = {
  id: 5,
  title: 'Dishes',
  household_id: 1,
  household_name: 'Flat',
}

function detail(overrides: Partial<ChoreStatsData> = {}): ChoreStatsData {
  return {
    chore_id: 4,
    title: 'Bins',
    range: '30d',
    granularity: 'day',
    people: [{ user_id: 1, first_name: 'Ava', last_name: 'One', done: 3, skipped: 1 }],
    over_time: [{ bucket: '2026-11-01', done: [{ user_id: 1, count: 3 }], skipped: 1 }],
    ...overrides,
  }
}

function gets(fetchMock: ReturnType<typeof mockFetch>, pattern: RegExp): string[] {
  return fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => pattern.test(url))
}

// Changes the page's filters without remounting the section, which is what the page itself does.
// A bare re-render would drop renderWithProviders' wrapper, remount, and lose the selection.
function Harness() {
  const [range, setRange] = useState<StatsRange>('30d')
  const [householdId, setHouseholdId] = useState('')
  return (
    <>
      <button type="button" onClick={() => setRange('90d')}>
        to 90d
      </button>
      <button type="button" onClick={() => setHouseholdId('2')}>
        to household 2
      </button>
      <ChoreStatsSection range={range} userId="" householdId={householdId} />
    </>
  )
}

async function pick(user: ReturnType<typeof userEvent.setup>, title: string) {
  await user.click(screen.getByRole('combobox', { name: 'Chore' }))
  await user.click(await screen.findByRole('option', { name: new RegExp(title) }))
}

describe('ChoreStatsSection', () => {
  it('shows only the picker and a hint until a chore is chosen', async () => {
    const fetchMock = mockFetch([{ path: OPTIONS, body: [BINS, DISHES] }])
    renderWithProviders(<ChoreStatsSection range="30d" userId="" householdId="" />)

    expect(await screen.findByRole('combobox', { name: 'Chore' })).toHaveTextContent(
      'Choose a chore…',
    )
    expect(
      screen.getByText('Pick a chore to see who completed and who skipped it.'),
    ).toBeInTheDocument()
    await waitFor(() => expect(gets(fetchMock, OPTIONS)).toHaveLength(1))
    expect(gets(fetchMock, DETAIL)).toHaveLength(0)
    expect(screen.queryByText('Completed and skipped per person')).not.toBeInTheDocument()
  })

  it('filters the options by what is typed', async () => {
    mockFetch([{ path: OPTIONS, body: [BINS, DISHES] }])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ChoreStatsSection range="30d" userId="" householdId="" />)

    await user.click(await screen.findByRole('combobox', { name: 'Chore' }))
    await user.type(await screen.findByPlaceholderText('Search chores…'), 'dish')

    await waitFor(() => expect(screen.queryByRole('option', { name: /Bins/ })).toBeNull())
    expect(screen.getByRole('option', { name: /Dishes/ })).toBeInTheDocument()
  })

  it('does not match on the chore id', async () => {
    // Each row's value is its id (titles can repeat), so a search for "4" must not find Bins.
    mockFetch([{ path: OPTIONS, body: [BINS, DISHES] }])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ChoreStatsSection range="30d" userId="" householdId="" />)

    await user.click(await screen.findByRole('combobox', { name: 'Chore' }))
    await user.type(await screen.findByPlaceholderText('Search chores…'), '4')
    expect(await screen.findByText('No chores found.')).toBeInTheDocument()
  })

  it('fetches the chosen chore with the range and person, and shows its charts', async () => {
    const fetchMock = mockFetch([
      { path: OPTIONS, body: [BINS, DISHES] },
      { path: DETAIL, body: detail() },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ChoreStatsSection range="7d" userId="2" householdId="" />)

    await screen.findByRole('combobox', { name: 'Chore' })
    await pick(user, 'Bins')

    expect(await screen.findByText('Completed and skipped per person')).toBeInTheDocument()
    expect(screen.getByText('Over time')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Chore' })).toHaveTextContent('Bins')
    const url = gets(fetchMock, DETAIL).at(-1)!
    expect(url).toContain('/api/v1/stats/chores/4?')
    expect(url).toContain('range=7d')
    expect(url).toContain('user_id=2')
  })

  it('refetches the chosen chore when the range changes', async () => {
    const fetchMock = mockFetch([
      { path: OPTIONS, body: [BINS] },
      { path: DETAIL, body: detail() },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Harness />)
    await screen.findByRole('combobox', { name: 'Chore' })
    await pick(user, 'Bins')
    await screen.findByText('Over time')

    await user.click(screen.getByRole('button', { name: 'to 90d' }))
    await waitFor(() => expect(gets(fetchMock, DETAIL).at(-1)).toContain('range=90d'))
  })

  it('says so when nobody touched the chore in the range', async () => {
    mockFetch([
      { path: OPTIONS, body: [BINS] },
      {
        path: DETAIL,
        body: detail({
          people: [{ user_id: 1, first_name: 'Ava', last_name: 'One', done: 0, skipped: 0 }],
          over_time: [{ bucket: '2026-11-01', done: [], skipped: 0 }],
        }),
      },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ChoreStatsSection range="30d" userId="" householdId="" />)
    await screen.findByRole('combobox', { name: 'Chore' })
    await pick(user, 'Bins')

    expect(
      await screen.findByText('Nobody completed or skipped this chore in this period.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Over time')).not.toBeInTheDocument()
  })

  it('shows an error when the chore fails to load', async () => {
    mockFetch([
      { path: OPTIONS, body: [BINS] },
      { path: DETAIL, status: 500, body: { detail: 'boom' } },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ChoreStatsSection range="30d" userId="" householdId="" />)
    await screen.findByRole('combobox', { name: 'Chore' })
    await pick(user, 'Bins')

    expect(await screen.findByText('Failed to load statistics')).toBeInTheDocument()
  })

  it('narrows the options by household and drops a selection it no longer holds', async () => {
    let call = 0
    const fetchMock = mockFetch([
      {
        path: OPTIONS,
        // First the unfiltered list, then household 2's, which does not hold Bins.
        body: () => (++call === 1 ? [BINS, DISHES] : [{ ...DISHES, household_id: 2 }]),
      },
      { path: DETAIL, body: detail() },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Harness />)
    await screen.findByRole('combobox', { name: 'Chore' })
    await pick(user, 'Bins')
    await screen.findByText('Over time')

    await user.click(screen.getByRole('button', { name: 'to household 2' }))

    await waitFor(() => expect(gets(fetchMock, OPTIONS).at(-1)).toContain('household_id=2'))
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Chore' })).toHaveTextContent('Choose a chore…'),
    )
    expect(screen.queryByText('Over time')).not.toBeInTheDocument()
  })

  it('drops the selection and its charts when the narrowed list fails to load', async () => {
    mockFetch([
      // Matched first: household 2's list fails, the unfiltered one loads.
      { path: /household_id=2/, status: 500, body: { detail: 'boom' } },
      { path: OPTIONS, body: [BINS] },
      { path: DETAIL, body: detail() },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Harness />)
    await screen.findByRole('combobox', { name: 'Chore' })
    await pick(user, 'Bins')
    await screen.findByText('Over time')

    await user.click(screen.getByRole('button', { name: 'to household 2' }))
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Chore' })).toHaveTextContent('Choose a chore…'),
    )
    expect(screen.queryByText('Over time')).not.toBeInTheDocument()
  })

  it('keeps a selection the narrowed list still holds', async () => {
    // The mirror of the test above, so "always clear on a household change" cannot pass both.
    mockFetch([
      { path: OPTIONS, body: [BINS, DISHES] },
      { path: DETAIL, body: detail() },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Harness />)
    await screen.findByRole('combobox', { name: 'Chore' })
    await pick(user, 'Bins')
    await screen.findByText('Over time')

    await user.click(screen.getByRole('button', { name: 'to household 2' }))
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Chore' })).toHaveTextContent('Bins'),
    )
    expect(await screen.findByText('Over time')).toBeInTheDocument()
  })

  it('names the household on each option when the chores span more than one', async () => {
    mockFetch([
      {
        path: OPTIONS,
        body: [BINS, { id: 9, title: 'Bins', household_id: 2, household_name: 'Cabin' }],
      },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ChoreStatsSection range="30d" userId="" householdId="" />)

    await user.click(await screen.findByRole('combobox', { name: 'Chore' }))
    const options = await screen.findAllByRole('option')
    expect(within(options[0]).getByText('Flat')).toBeInTheDocument()
    expect(within(options[1]).getByText('Cabin')).toBeInTheDocument()
  })
})
