import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import ConfirmAccount from './ConfirmAccount'
import { renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

const tokenInfo = { email: 'newbie@example.com', first_name: 'New', last_name: 'Bie' }

const tree = (
  <Routes>
    <Route path="/confirm" element={<ConfirmAccount />} />
    <Route path="/" element={<div>home-marker</div>} />
  </Routes>
)

describe('ConfirmAccount', () => {
  it('sets the password and logs in on a valid link', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'GET') return jsonBody(tokenInfo)
      return jsonBody(makeUser({ email: 'newbie@example.com' }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { value } = renderWithProviders(tree, { route: '/confirm?token=abc123' })

    // Greeting shows the email once the token resolves.
    expect(await screen.findByText(/newbie@example.com/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Password'), 'brandnewpass123')
    await user.type(screen.getByLabelText('Confirm password'), 'brandnewpass123')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/confirm/abc123',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    await waitFor(() => expect(screen.getByText('home-marker')).toBeInTheDocument())
    expect(value.refresh).toHaveBeenCalled()
  })

  it('shows an invalid state when the token is bad', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonBody({ detail: 'Invalid or expired confirmation link' }, 404)),
    )
    renderWithProviders(tree, { route: '/confirm?token=bogus' })

    expect(await screen.findByText('Link expired or invalid')).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('rejects mismatched passwords without calling the API', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'GET') return jsonBody(tokenInfo)
      return jsonBody({}, 200)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(tree, { route: '/confirm?token=abc123' })
    await screen.findByText(/newbie@example.com/)

    await user.type(screen.getByLabelText('Password'), 'brandnewpass123')
    await user.type(screen.getByLabelText('Confirm password'), 'different12345')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    expect(await screen.findByText('The passwords do not match')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([, i]) => i?.method === 'POST')).toHaveLength(0)
  })

  it('rejects a too-short password without calling the API', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'GET') return jsonBody(tokenInfo)
      return jsonBody({}, 200)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(tree, { route: '/confirm?token=abc123' })
    await screen.findByText(/newbie@example.com/)

    await user.type(screen.getByLabelText('Password'), 'short')
    await user.type(screen.getByLabelText('Confirm password'), 'short')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    expect(
      await screen.findByText('The password must be at least 8 characters'),
    ).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([, i]) => i?.method === 'POST')).toHaveLength(0)
  })
})
