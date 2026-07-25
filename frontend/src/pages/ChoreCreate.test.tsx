import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import ChoreCreate from './ChoreCreate'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeChore, makeHousehold, makeHouseholdMember, makeTag, makeUser } from '../test/fixtures'
import type { Page } from '../lib/types'

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

// The members and tags endpoints carry a query string, so match them by pattern.
const MEMBERS = /\/api\/v1\/households\/\d+\/members/
const TAGS = /\/api\/v1\/tags(\?|$)/

function page<T>(items: T[]): Page<T> {
  return { items, total: items.length, page: 1, page_size: 100 }
}

function postBody(mock: ReturnType<typeof mockFetch>): Record<string, unknown> {
  const call = mock.mock.calls.find(([, init]) => init?.method === 'POST')
  if (!call) throw new Error('no POST call recorded')
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>
}

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

// A single-household set of mocks (the common case).
function singleHouseholdMocks() {
  return mockFetch([
    { path: /\/api\/v1\/households(\?|$)/, method: 'GET', body: page([makeHousehold({ id: 1 })]) },
    {
      path: MEMBERS,
      method: 'GET',
      body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
    },
    { path: TAGS, method: 'GET', body: page([makeTag({ id: 3, name: 'deep-clean' })]) },
    { path: '/api/v1/chores', method: 'POST', status: 201, body: makeChore() },
  ])
}

function withRoutes(state?: unknown) {
  return renderWithProviders(
    <Routes>
      <Route path="/chores/new" element={<ChoreCreate />} />
      <Route path="/chores" element={<div>chores-list</div>} />
    </Routes>,
    { authValue: { user: me }, route: '/chores/new', state },
  )
}

// The prefill payload a chore's "Clone" action pushes into router state.
function cloneState(overrides: Record<string, unknown> = {}) {
  return {
    clone: {
      household_id: 1,
      title: 'Scrub the tub',
      description: 'Do it well',
      start_date: '2026-07-16',
      repeats: 'daily',
      assignment_type: 'least_done',
      assignee_ids: [2],
      tag_ids: [3],
      repeat_interval: 1,
      weekdays: [],
      ...overrides,
    },
  }
}

describe('ChoreCreate', () => {
  it('renders member and tag options after loading', async () => {
    singleHouseholdMocks()
    renderWithProviders(<ChoreCreate />, { authValue: { user: me }, route: '/chores/new' })

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    // Members and tags both live behind searchable multi-selects; open each to
    // see their options.
    await user.click(await screen.findByRole('button', { name: 'Assignees' }))
    expect(await screen.findByRole('option', { name: 'Jo Ng' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.getByLabelText('Title')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Tags' }))
    expect(await screen.findByRole('option', { name: 'deep-clean' })).toBeInTheDocument()
  })

  it('labels the notes field as Description', async () => {
    singleHouseholdMocks()
    renderWithProviders(<ChoreCreate />, { authValue: { user: me }, route: '/chores/new' })

    expect(await screen.findByLabelText('Description')).toBeInTheDocument()
    expect(screen.queryByLabelText('Notes')).not.toBeInTheDocument()
  })

  it('hides the household select for a single household but still sends household_id', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    await screen.findByLabelText('Title')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Title'), 'Scrub the tub')
    await userEvent.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({ title: 'Scrub the tub', household_id: 1 })
  })

  it('creates a chore with the selected assignees and tags, then navigates', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Scrub the tub')
    // Pick the assignee via the searchable multi-select, then close it.
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    await user.keyboard('{Escape}')
    // Pick the tag via the searchable multi-select, then close it.
    await user.click(screen.getByRole('button', { name: 'Tags' }))
    await user.click(await screen.findByRole('option', { name: 'deep-clean' }))
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('combobox', { name: 'Repeats' }))
    await user.click(await screen.findByRole('option', { name: 'Daily' }))
    await user.click(screen.getByRole('combobox', { name: 'Assignment' }))
    await user.click(await screen.findByRole('option', { name: 'Least done' }))
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    expect(await screen.findByText('chores-list')).toBeInTheDocument()
    expect(postBody(fetchMock)).toMatchObject({
      title: 'Scrub the tub',
      household_id: 1,
      repeats: 'daily',
      assignment_type: 'least_done',
      assignee_ids: [2],
      tag_ids: [3],
      // Unset recurrence detail: every period, unpinned.
      repeat_interval: 1,
      weekdays: null,
    })
  })

  it('pins the selected weekdays, reporting them Monday-first', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Washing machine')
    // Weekly is the default, so the weekday row already shows. Click out of order.
    await user.click(screen.getByRole('button', { name: 'Friday' }))
    await user.click(screen.getByRole('button', { name: 'Tuesday' }))
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({ repeats: 'weekly', weekdays: [1, 4] })
  })

  it('submits a typed interval and names the period beside it', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Dishwasher')
    await user.click(screen.getByRole('combobox', { name: 'Repeats' }))
    await user.click(await screen.findByRole('option', { name: 'Daily' }))
    // The unit agrees with the number in the box, singular at one.
    expect(screen.getByText('day')).toBeInTheDocument()
    await user.clear(screen.getByLabelText('Repeat every'))
    await user.type(screen.getByLabelText('Repeat every'), '14')
    expect(screen.getByLabelText('Repeat every')).toHaveValue(14)
    expect(screen.getByText('days')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({ repeats: 'daily', repeat_interval: 14 })
  })

  it('hides both recurrence controls for a one-off and submits them unset', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Fix the shelf')
    await user.click(screen.getByRole('combobox', { name: 'Repeats' }))
    await user.click(await screen.findByRole('option', { name: 'Manual' }))

    expect(screen.queryByLabelText('Repeat every')).not.toBeInTheDocument()
    expect(screen.queryByRole('toolbar', { name: 'On these days' })).not.toBeInTheDocument()
    expect(screen.queryByText(/without pinning a day/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({ repeat_interval: 1, weekdays: null })
  })

  it('drops pinned weekdays when the period stops being weekly, keeping the interval', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Deep clean')
    await user.click(screen.getByRole('button', { name: 'Tuesday' }))
    await user.clear(screen.getByLabelText('Repeat every'))
    await user.type(screen.getByLabelText('Repeat every'), '3')
    // Monthly cannot be pinned, so the row goes away and the stale day must not be sent.
    await user.click(screen.getByRole('combobox', { name: 'Repeats' }))
    await user.click(await screen.findByRole('option', { name: 'Monthly' }))
    expect(screen.queryByRole('toolbar', { name: 'On these days' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({
      repeats: 'monthly',
      repeat_interval: 3,
      weekdays: null,
    })
  })

  it('falls back to an interval of one when the field is cleared', async () => {
    // Only the cleared case is worth testing: min={1} makes 0 a native constraint
    // violation, so the click might never reach the submit handler at all.
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Bins')
    await user.clear(screen.getByLabelText('Repeat every'))
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({ repeat_interval: 1 })
  })

  it('bounds the interval to what the API accepts', async () => {
    // The bound mirrors the backend's MAX_INTERVAL. It matters because an over-cap value
    // comes back as a pydantic 422 whose `detail` is a list, which the api wrapper cannot
    // translate, so the form would surface the browser's own untranslated status text.
    // Asserted as the attribute rather than by typing 9999 and submitting: `max` makes
    // that a native constraint violation, so the click never reaches the submit handler
    // (the same reason there is no "typing 0" case for `min`).
    singleHouseholdMocks()
    withRoutes()

    const field = await screen.findByLabelText('Repeat every')
    expect(field).toHaveAttribute('min', '1')
    expect(field).toHaveAttribute('max', '365')
  })

  it('shows take turns only for auto strategies and the current-assignee picker only for manual', async () => {
    singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await screen.findByLabelText('Title')
    // Manual is the default: no take-turns checkbox, and no current-assignee picker
    // until the pool has a member.
    expect(screen.queryByRole('checkbox', { name: 'Take turns' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('combobox', { name: 'Currently assigned to' }),
    ).not.toBeInTheDocument()

    // Switching to an auto strategy reveals take turns and hides the current picker.
    await user.click(screen.getByRole('combobox', { name: 'Assignment' }))
    await user.click(await screen.findByRole('option', { name: 'Alphabetical' }))
    expect(screen.getByRole('checkbox', { name: 'Take turns' })).toBeInTheDocument()
    expect(
      screen.queryByRole('combobox', { name: 'Currently assigned to' }),
    ).not.toBeInTheDocument()
  })

  it('submits a turn length when take turns is enabled', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Water plants')
    await user.click(screen.getByRole('combobox', { name: 'Assignment' }))
    await user.click(await screen.findByRole('option', { name: 'Alphabetical' }))
    await user.click(screen.getByRole('checkbox', { name: 'Take turns' }))
    // The turn-length field appears (defaulting to 2) once take turns is on, and
    // accepts a multi-digit value (the field is string-backed, so it can be cleared).
    const turnLength = screen.getByLabelText('Turn length')
    expect(turnLength).toHaveValue(2)
    await user.clear(turnLength)
    await user.type(turnLength, '14')
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({
      assignment_type: 'alphabetical',
      turn_length: 14,
    })
  })

  it('resets the current assignee to shared when it is removed from the pool', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Dishes')
    // Manual: add Jo and pick them as the current assignee.
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('combobox', { name: 'Currently assigned to' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    // Remove Jo from the pool: the current-assignee picker disappears and submit
    // sends current_assignee_id: null (shared) rather than a stale id.
    await user.click(screen.getByRole('button', { name: 'Remove Jo Ng' }))
    expect(
      screen.queryByRole('combobox', { name: 'Currently assigned to' }),
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({ assignee_ids: [], current_assignee_id: null })
  })

  it('lets manual pick the current assignee and submits it', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Dishes')
    // Manual (the default): pick a pool member, which reveals the current-assignee select.
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('combobox', { name: 'Currently assigned to' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({
      assignment_type: 'manual',
      current_assignee_id: 2,
      turn_length: 1,
    })
  })

  it('lets a multi-household user pick the household and resets stale assignees', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const path = url.split('?')[0]
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'GET' && path.endsWith('/api/v1/households')) {
        return jsonBody(
          page([
            makeHousehold({ id: 1, name: 'Flat 3B' }),
            makeHousehold({ id: 2, name: 'Beach House' }),
          ]),
        )
      }
      if (method === 'GET' && /\/households\/1\/members/.test(url)) {
        return jsonBody(page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]))
      }
      if (method === 'GET' && /\/households\/2\/members/.test(url)) {
        return jsonBody(page([makeHouseholdMember({ id: 5, first_name: 'Mia', last_name: 'Fox' })]))
      }
      if (method === 'GET' && path.endsWith('/api/v1/tags')) return jsonBody(page([]))
      if (method === 'POST' && path.endsWith('/api/v1/chores')) return jsonBody(makeChore(), 201)
      return jsonBody(undefined, 204)
    })
    vi.stubGlobal('fetch', fetchMock)
    withRoutes()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    // Defaults to the lowest-id household (Flat 3B) and its member.
    await user.type(await screen.findByLabelText('Title'), 'Scrub the tub')
    await user.click(await screen.findByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    await user.keyboard('{Escape}')

    // Switch to Beach House: its member appears in the picker, the previous one is gone.
    await user.click(screen.getByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))
    await user.click(await screen.findByRole('button', { name: 'Assignees' }))
    expect(await screen.findByRole('option', { name: 'Mia Fox' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Jo Ng' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('option', { name: 'Mia Fox' }))
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    const body = JSON.parse(String(call[1]?.body)) as Record<string, unknown>
    // The chore lands in Beach House with only its own member (Jo Ng dropped).
    expect(body).toMatchObject({ household_id: 2, assignee_ids: [5] })
  })

  it('picks a start date from the calendar and submits it', async () => {
    const fetchMock = mockFetch([
      {
        path: /\/api\/v1\/households(\?|$)/,
        method: 'GET',
        body: page([makeHousehold({ id: 1 })]),
      },
      { path: MEMBERS, method: 'GET', body: page([]) },
      { path: TAGS, method: 'GET', body: page([]) },
      { path: '/api/v1/chores', method: 'POST', status: 201, body: makeChore() },
    ])
    withRoutes()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.type(await screen.findByLabelText('Title'), 'Dust the shelves')
    await user.click(screen.getByRole('button', { name: /Start date/ }))
    await user.click(await screen.findByText('15'))
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(String(postBody(fetchMock).start_date)).toMatch(/-15$/)
  })

  it('carries the recurrence detail through a clone', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes(cloneState({ repeats: 'weekly', repeat_interval: 3, weekdays: [1, 4] }))
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByLabelText('Title')
    expect(screen.getByLabelText('Repeat every')).toHaveValue(3)
    expect(screen.getByRole('button', { name: 'Tuesday' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Friday' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Monday' })).toHaveAttribute('aria-pressed', 'false')

    await user.click(screen.getByRole('button', { name: 'Add chore' }))
    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({ repeat_interval: 3, weekdays: [1, 4] })
  })

  it('prefills the form from clone state and creates a faithful copy in the same household', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes(cloneState())
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    // Fields are seeded from the source chore, and its assignee is pre-selected.
    expect(await screen.findByLabelText('Title')).toHaveValue('Scrub the tub')
    expect(screen.getByLabelText('Description')).toHaveValue('Do it well')
    const assigneeTrigger = await screen.findByRole('button', { name: 'Assignees' })
    expect(within(assigneeTrigger).getByText('Jo Ng')).toBeInTheDocument()
    // Same household as the source, so nothing is dropped and no note shows.
    expect(screen.queryByText(/were not added/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    expect(postBody(fetchMock)).toMatchObject({
      household_id: 1,
      title: 'Scrub the tub',
      description: 'Do it well',
      start_date: '2026-07-16',
      repeats: 'daily',
      assignment_type: 'least_done',
      assignee_ids: [2],
      tag_ids: [3],
    })
  })

  it('drops clone assignees/tags absent from the chosen household and notes it', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const path = url.split('?')[0]
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'GET' && path.endsWith('/api/v1/households')) {
        return jsonBody(
          page([
            makeHousehold({ id: 1, name: 'Flat 3B' }),
            makeHousehold({ id: 2, name: 'Beach House' }),
          ]),
        )
      }
      if (method === 'GET' && /\/households\/1\/members/.test(url)) {
        return jsonBody(page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]))
      }
      if (method === 'GET' && /\/households\/2\/members/.test(url)) {
        return jsonBody(page([makeHouseholdMember({ id: 5, first_name: 'Mia', last_name: 'Fox' })]))
      }
      if (method === 'GET' && path.endsWith('/api/v1/tags')) {
        // Only the source household (1) owns the cloned tag.
        return url.includes('household_id=1')
          ? jsonBody(page([makeTag({ id: 3, name: 'deep-clean' })]))
          : jsonBody(page([]))
      }
      if (method === 'POST' && path.endsWith('/api/v1/chores')) return jsonBody(makeChore(), 201)
      return jsonBody(undefined, 204)
    })
    vi.stubGlobal('fetch', fetchMock)
    withRoutes(cloneState())
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    // Opens in the source household with its assignee prefilled and no note.
    const assigneeTrigger = await screen.findByRole('button', { name: 'Assignees' })
    expect(within(assigneeTrigger).getByText('Jo Ng')).toBeInTheDocument()
    expect(screen.queryByText(/were not added/)).not.toBeInTheDocument()

    // Switch to Beach House: the source's assignee and tag don't belong there.
    await user.click(screen.getByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))

    // The dropped-assignee/tag note appears once members/tags reload.
    expect(await screen.findByText(/1 assignee was not added/)).toBeInTheDocument()
    expect(screen.getByText(/1 tag was not added/)).toBeInTheDocument()
    // The picker now offers Beach House's member, not the source's.
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    expect(await screen.findByRole('option', { name: 'Mia Fox' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Jo Ng' })).not.toBeInTheDocument()
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    await screen.findByText('chores-list')
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    const body = JSON.parse(String(call[1]?.body)) as Record<string, unknown>
    // Lands in Beach House with the non-member assignee and tag dropped.
    expect(body).toMatchObject({ household_id: 2, assignee_ids: [], tag_ids: [] })
  })

  it('surfaces a create error and stays on the form', async () => {
    mockFetch([
      {
        path: /\/api\/v1\/households(\?|$)/,
        method: 'GET',
        body: page([makeHousehold({ id: 1 })]),
      },
      { path: MEMBERS, method: 'GET', body: page([]) },
      { path: TAGS, method: 'GET', body: page([]) },
      {
        path: '/api/v1/chores',
        method: 'POST',
        status: 400,
        body: { detail: 'Tags must belong to your household' },
      },
    ])
    renderWithProviders(<ChoreCreate />, { authValue: { user: me }, route: '/chores/new' })

    await userEvent.type(await screen.findByLabelText('Title'), 'Something')
    await userEvent.click(screen.getByRole('button', { name: 'Add chore' }))

    expect(await screen.findByText('Tags must belong to your household')).toBeInTheDocument()
  })
})
