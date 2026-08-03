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
  return renderWithProviders(
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

  it('re-reads the session so the new organiser role reaches the sidebar', async () => {
    // Creating a household makes you its organiser. The sidebar and RequireRole read that from
    // the auth context, which login populated when the account had no household at all, so
    // without this a fresh user creates their first household and the management pages keep
    // bouncing them to Home until they reload by hand. That is the documented first step for
    // every new account, so it is the most-travelled path in the app.
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonBody(makeHousehold({ id: 9, name: 'Beach House' }), 201),
    )
    const { value } = renderCreate(fetchMock)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Name'), 'Beach House')
    await user.click(screen.getByRole('button', { name: 'Add household' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true)
  })

  it('does not re-read the session when the create fails', async () => {
    // Nothing changed server-side, so there is nothing to adopt. Waits on the error actually
    // appearing rather than on a timeout, so the assertion below runs after the handler has
    // finished rather than before it got there.
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonBody({ detail: 'Name is required' }, 422),
    )
    const { value } = renderCreate(fetchMock)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Name'), 'Beach House')
    await user.click(screen.getByRole('button', { name: 'Add household' }))

    expect(await screen.findByText('Name is required')).toBeInTheDocument()
    expect(value.refresh).not.toHaveBeenCalled()
  })
})
