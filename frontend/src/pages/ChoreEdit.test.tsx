import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import ChoreEdit from './ChoreEdit'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeChore, makeHouseholdMember, makeTag, makeUser } from '../test/fixtures'
import type { Page } from '../lib/types'

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

const MEMBERS = /\/api\/v1\/households\/\d+\/members/
const TAGS = /\/api\/v1\/tags(\?|$)/

function page<T>(items: T[]): Page<T> {
  return { items, total: items.length, page: 1, page_size: 100 }
}

function patchBody(mock: ReturnType<typeof mockFetch>): Record<string, unknown> {
  const call = mock.mock.calls.find(([, init]) => init?.method === 'PATCH')
  if (!call) throw new Error('no PATCH call recorded')
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>
}

const savedChore = makeChore({
  id: 7,
  title: 'Scrub the tub',
  description: 'Old notes',
  household: { id: 4, name: 'Beach House' },
  assignees: [makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
  tags: [makeTag({ id: 3, name: 'deep-clean' })],
})

function editMocks(overrides: { patchStatus?: number; patchBody?: unknown } = {}) {
  return mockFetch([
    { path: '/api/v1/chores/7', method: 'GET', body: savedChore },
    {
      path: MEMBERS,
      method: 'GET',
      body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
    },
    { path: TAGS, method: 'GET', body: [makeTag({ id: 3, name: 'deep-clean' })] },
    {
      path: '/api/v1/chores/7',
      method: 'PATCH',
      status: overrides.patchStatus ?? 200,
      body: overrides.patchBody ?? savedChore,
    },
  ])
}

function renderEdit() {
  return renderWithProviders(
    <Routes>
      <Route path="/chores/:id/edit" element={<ChoreEdit />} />
      <Route path="/chores" element={<div>chores-list</div>} />
    </Routes>,
    { authValue: { user: me }, route: '/chores/7/edit' },
  )
}

describe('ChoreEdit', () => {
  it('pre-fills the form and shows the household read-only', async () => {
    editMocks()
    renderEdit()

    expect(await screen.findByDisplayValue('Scrub the tub')).toBeInTheDocument()
    // The household is shown but is not an editable control.
    expect(screen.getByText('Beach House')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    // Its assignee is pre-selected.
    expect(screen.getByRole('button', { name: 'Jo Ng' })).toBeInTheDocument()
  })

  it('saves changes with a PATCH that omits the household, then navigates', async () => {
    const fetchMock = editMocks()
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    const title = await screen.findByDisplayValue('Scrub the tub')
    await user.clear(title)
    await user.type(title, 'Deep clean the tub')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText('chores-list')).toBeInTheDocument()
    const body = patchBody(fetchMock)
    expect(body).toMatchObject({ title: 'Deep clean the tub', assignee_ids: [2], tag_ids: [3] })
    expect(body).not.toHaveProperty('household_id')
  })

  it('surfaces an update error and stays on the form', async () => {
    editMocks({
      patchStatus: 400,
      patchBody: { detail: 'Assignees must be members of your household' },
    })
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Save changes' }))

    expect(
      await screen.findByText('Assignees must be members of your household'),
    ).toBeInTheDocument()
  })
})
