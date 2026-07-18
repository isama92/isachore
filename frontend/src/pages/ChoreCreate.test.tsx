import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
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

function withRoutes() {
  return renderWithProviders(
    <Routes>
      <Route path="/chores/new" element={<ChoreCreate />} />
      <Route path="/chores" element={<div>chores-list</div>} />
    </Routes>,
    { authValue: { user: me }, route: '/chores/new' },
  )
}

describe('ChoreCreate', () => {
  it('renders member and tag options after loading', async () => {
    singleHouseholdMocks()
    renderWithProviders(<ChoreCreate />, { authValue: { user: me }, route: '/chores/new' })

    expect(await screen.findByRole('button', { name: 'Jo Ng' })).toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toBeInTheDocument()
    // Tags live behind a searchable multi-select; open it to see the options.
    const user = userEvent.setup({ pointerEventsCheck: 0 })
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
    await user.click(screen.getByRole('button', { name: 'Jo Ng' }))
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
    await user.click(await screen.findByRole('button', { name: 'Jo Ng' }))

    // Switch to Beach House: its member appears, the previous one is gone.
    await user.click(screen.getByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))
    expect(await screen.findByRole('button', { name: 'Mia Fox' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Jo Ng' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Mia Fox' }))
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
