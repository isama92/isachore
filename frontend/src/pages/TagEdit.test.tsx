import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import TagEdit from './TagEdit'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeTag, makeUser } from '../test/fixtures'

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

const savedTag = makeTag({ id: 7, name: 'deep-clean', color: '#0d9488' })

function patchBody(mock: ReturnType<typeof mockFetch>): Record<string, unknown> {
  const call = mock.mock.calls.find(([, init]) => init?.method === 'PATCH')
  if (!call) throw new Error('no PATCH call recorded')
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>
}

function editMocks(overrides: { patchStatus?: number; patchBody?: unknown } = {}) {
  return mockFetch([
    { path: '/api/v1/tags/7', method: 'GET', body: savedTag },
    {
      path: '/api/v1/tags/7',
      method: 'PATCH',
      status: overrides.patchStatus ?? 200,
      body: overrides.patchBody ?? savedTag,
    },
  ])
}

function renderEdit() {
  return renderWithProviders(
    <Routes>
      <Route path="/tags/:id/edit" element={<TagEdit />} />
      <Route path="/tags" element={<div>tags-list</div>} />
    </Routes>,
    { authValue: { user: me }, route: '/tags/7/edit' },
  )
}

describe('TagEdit', () => {
  it('pre-fills the form with the existing tag', async () => {
    editMocks()
    renderEdit()
    expect(await screen.findByDisplayValue('deep-clean')).toBeInTheDocument()
  })

  it('saves changes with a PATCH, then navigates', async () => {
    const fetchMock = editMocks()
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    const name = await screen.findByDisplayValue('deep-clean')
    await user.clear(name)
    await user.type(name, 'sparkle')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText('tags-list')).toBeInTheDocument()
    expect(patchBody(fetchMock)).toMatchObject({ name: 'sparkle', color: '#0d9488' })
  })

  it('shows a not-found message when the tag is missing', async () => {
    mockFetch([
      { path: '/api/v1/tags/7', method: 'GET', status: 404, body: { detail: 'Tag not found' } },
    ])
    renderEdit()
    expect(await screen.findByText('Tag not found')).toBeInTheDocument()
  })

  it('surfaces an update error and stays on the form', async () => {
    editMocks({ patchStatus: 409, patchBody: { detail: 'A tag with this name already exists' } })
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('A tag with this name already exists')).toBeInTheDocument()
  })
})
