import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import ChoreCreate from './ChoreCreate'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeChore, makeHousehold, makeHouseholdMember, makeTag, makeUser } from '../test/fixtures'
import type { Page } from '../lib/types'

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

// The members endpoint carries a query string, so match it by pattern.
const MEMBERS = /\/api\/v1\/households\/\d+\/members/

function page<T>(items: T[]): Page<T> {
  return { items, total: items.length, page: 1, page_size: 100 }
}

function postBody(mock: ReturnType<typeof mockFetch>): Record<string, unknown> {
  const call = mock.mock.calls.find(([, init]) => init?.method === 'POST')
  if (!call) throw new Error('no POST call recorded')
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>
}

describe('ChoreCreate', () => {
  it('renders member and tag options after loading', async () => {
    mockFetch([
      {
        path: /\/api\/v1\/households(\?|$)/,
        method: 'GET',
        body: page([makeHousehold({ id: 1 })]),
      },
      {
        path: MEMBERS,
        method: 'GET',
        body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
      },
      { path: '/api/v1/tags', method: 'GET', body: [makeTag({ id: 3, name: 'deep-clean' })] },
    ])
    renderWithProviders(<ChoreCreate />, { authValue: { user: me }, route: '/chores/new' })

    expect(await screen.findByRole('button', { name: 'Jo Ng' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'deep-clean' })).toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toBeInTheDocument()
  })

  it('creates a chore with the selected assignees and tags, then navigates', async () => {
    const fetchMock = mockFetch([
      {
        path: /\/api\/v1\/households(\?|$)/,
        method: 'GET',
        body: page([makeHousehold({ id: 1 })]),
      },
      {
        path: MEMBERS,
        method: 'GET',
        body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
      },
      { path: '/api/v1/tags', method: 'GET', body: [makeTag({ id: 3, name: 'deep-clean' })] },
      { path: '/api/v1/chores', method: 'POST', status: 201, body: makeChore() },
    ])
    renderWithProviders(
      <Routes>
        <Route path="/chores/new" element={<ChoreCreate />} />
        <Route path="/chores" element={<div>chores-list</div>} />
      </Routes>,
      { authValue: { user: me }, route: '/chores/new' },
    )

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.type(await screen.findByLabelText('Title'), 'Scrub the tub')
    await user.click(screen.getByRole('button', { name: 'Jo Ng' }))
    await user.click(screen.getByRole('button', { name: 'deep-clean' }))
    await user.click(screen.getByRole('combobox', { name: 'Repeats' }))
    await user.click(await screen.findByRole('option', { name: 'Daily' }))
    await user.click(screen.getByRole('combobox', { name: 'Assignment' }))
    await user.click(await screen.findByRole('option', { name: 'Least done' }))
    await user.click(screen.getByRole('button', { name: 'Add chore' }))

    expect(await screen.findByText('chores-list')).toBeInTheDocument()
    expect(postBody(fetchMock)).toMatchObject({
      title: 'Scrub the tub',
      repeats: 'daily',
      assignment_type: 'least_done',
      assignee_ids: [2],
      tag_ids: [3],
    })
  })

  it('picks a start date from the calendar and submits it', async () => {
    const fetchMock = mockFetch([
      {
        path: /\/api\/v1\/households(\?|$)/,
        method: 'GET',
        body: page([makeHousehold({ id: 1 })]),
      },
      { path: MEMBERS, method: 'GET', body: page([]) },
      { path: '/api/v1/tags', method: 'GET', body: [] },
      { path: '/api/v1/chores', method: 'POST', status: 201, body: makeChore() },
    ])
    renderWithProviders(
      <Routes>
        <Route path="/chores/new" element={<ChoreCreate />} />
        <Route path="/chores" element={<div>chores-list</div>} />
      </Routes>,
      { authValue: { user: me }, route: '/chores/new' },
    )
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
      { path: '/api/v1/tags', method: 'GET', body: [] },
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
