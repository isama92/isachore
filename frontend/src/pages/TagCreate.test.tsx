import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import TagCreate from './TagCreate'
import { mockFetch, renderWithProviders, membershipsFor } from '../test/utils'
import { makeHousehold, makeTag, makeUser } from '../test/fixtures'
import type { Page } from '../lib/types'

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

const HOUSEHOLDS = /\/api\/v1\/households(\?|$)/

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

function singleHouseholdMocks() {
  return mockFetch([
    { path: HOUSEHOLDS, method: 'GET', body: page([makeHousehold({ id: 1 })]) },
    { path: '/api/v1/tags', method: 'POST', status: 201, body: makeTag() },
  ])
}

function withRoutes() {
  return renderWithProviders(
    <Routes>
      <Route path="/tags/new" element={<TagCreate />} />
      <Route path="/tags" element={<div>tags-list</div>} />
    </Routes>,
    {
      authValue: { user: me, memberships: membershipsFor('organiser', 1, 2) },
      route: '/tags/new',
    },
  )
}

describe('TagCreate', () => {
  it('renders the name and colour fields after loading', async () => {
    singleHouseholdMocks()
    renderWithProviders(<TagCreate />, { authValue: { user: me }, route: '/tags/new' })
    expect(await screen.findByLabelText('Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Colour')).toBeInTheDocument()
  })

  it('hides the household select for a single household but still sends household_id', async () => {
    const fetchMock = singleHouseholdMocks()
    withRoutes()

    await screen.findByLabelText('Name')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Name'), 'urgent')
    await userEvent.click(screen.getByRole('button', { name: 'Add tag' }))

    await screen.findByText('tags-list')
    expect(postBody(fetchMock)).toMatchObject({
      name: 'urgent',
      household_id: 1,
      color: '#0d9488',
    })
  })

  it('lets a multi-household user pick the target household', async () => {
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
      if (method === 'POST' && path.endsWith('/api/v1/tags')) return jsonBody(makeTag(), 201)
      return jsonBody(undefined, 204)
    })
    vi.stubGlobal('fetch', fetchMock)
    withRoutes()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.type(await screen.findByLabelText('Name'), 'beach-only')
    await user.click(screen.getByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))
    await user.click(screen.getByRole('button', { name: 'Add tag' }))

    await screen.findByText('tags-list')
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    const body = JSON.parse(String(call[1]?.body)) as Record<string, unknown>
    expect(body).toMatchObject({ name: 'beach-only', household_id: 2 })
  })

  it('surfaces a duplicate-name error and stays on the form', async () => {
    mockFetch([
      { path: HOUSEHOLDS, method: 'GET', body: page([makeHousehold({ id: 1 })]) },
      {
        path: '/api/v1/tags',
        method: 'POST',
        status: 409,
        body: { detail: 'A tag with this name already exists' },
      },
    ])
    renderWithProviders(<TagCreate />, { authValue: { user: me }, route: '/tags/new' })

    await userEvent.type(await screen.findByLabelText('Name'), 'shared')
    await userEvent.click(screen.getByRole('button', { name: 'Add tag' }))

    expect(await screen.findByText('A tag with this name already exists')).toBeInTheDocument()
  })

  it('offers only the households the user organises', async () => {
    // Submitting into a household the caller only deputises in would 403, so it must not be
    // offered. With one organised household left the picker hides entirely (it renders above
    // one), which is what makes this observable.
    const fetchMock = mockFetch([
      {
        path: HOUSEHOLDS,
        method: 'GET',
        body: page([
          makeHousehold({ id: 1, name: 'Flat 3B' }),
          makeHousehold({ id: 2, name: 'Beach House' }),
        ]),
      },
      { path: '/api/v1/tags', method: 'POST', status: 201, body: makeTag() },
    ])
    renderWithProviders(
      <Routes>
        <Route path="/tags/new" element={<TagCreate />} />
        <Route path="/tags" element={<div>tags-list</div>} />
      </Routes>,
      {
        authValue: {
          user: me,
          memberships: [
            { household_id: 1, role: 'organiser', owned: false },
            { household_id: 2, role: 'deputy', owned: false },
          ],
        },
        route: '/tags/new',
      },
    )
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.type(await screen.findByLabelText('Name'), 'deep-clean')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add tag' }))

    // The positive half: an absent picker is also what a dead fixture looks like, so assert
    // the surviving household is what actually reaches the wire.
    await screen.findByText('tags-list')
    expect(postBody(fetchMock)).toMatchObject({ household_id: 1 })
  })
})
