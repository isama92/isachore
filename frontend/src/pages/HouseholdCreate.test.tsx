import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import HouseholdCreate from './HouseholdCreate'
import { renderWithProviders } from '../test/utils'
import { makeHousehold, makeUser } from '../test/fixtures'

const me = makeUser({ id: 1 })

type FetchMock = ReturnType<typeof vi.fn>

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

function renderCreate(fetchMock: FetchMock) {
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(
    <Routes>
      <Route path="/households/new" element={<HouseholdCreate />} />
      <Route path="/households" element={<div>households-list</div>} />
    </Routes>,
    { authValue: { user: me }, route: '/households/new' },
  )
}

describe('HouseholdCreate', () => {
  it('posts the name and navigates back to the list', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonBody(makeHousehold({ id: 9, name: 'Beach House' }), 201),
    )
    renderCreate(fetchMock)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Name'), 'Beach House')
    await user.click(screen.getByRole('button', { name: 'Add household' }))

    expect(await screen.findByText('households-list')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(post).toBeTruthy()
    expect(JSON.parse(String(post![1]?.body))).toEqual({ name: 'Beach House' })
  })

  it('surfaces a create error and stays on the form', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonBody({ detail: 'Name is required' }, 422),
    )
    renderCreate(fetchMock)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Name'), 'x')
    await user.click(screen.getByRole('button', { name: 'Add household' }))

    expect(await screen.findByText('Name is required')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('households-list')).not.toBeInTheDocument())
  })
})
