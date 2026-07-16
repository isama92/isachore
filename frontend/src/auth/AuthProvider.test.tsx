import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AuthProvider from './AuthProvider'
import { useAuth } from './useAuth'
import { jsonResponse, mockFetch } from '../test/utils'
import { makeMe, makeUser } from '../test/fixtures'

function Harness() {
  const { user, impersonating, loading, login, logout, refresh } = useAuth()
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user ? user.email : 'none'}</span>
      <span data-testid="impersonating">{String(impersonating)}</span>
      <button onClick={() => void login('a@example.com', 'password12345')}>login</button>
      <button onClick={() => void logout()}>logout</button>
      <button onClick={() => void refresh()}>refresh</button>
    </div>
  )
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Harness />
    </AuthProvider>,
  )
}

describe('AuthProvider', () => {
  it('useAuth throws when used outside a provider', () => {
    function Orphan() {
      useAuth()
      return null
    }
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Orphan />)).toThrow('useAuth must be used within <AuthProvider>')
    spy.mockRestore()
  })

  it('loads the current user on mount', async () => {
    mockFetch([
      {
        path: '/api/v1/auth/me',
        body: makeMe({ email: 'admin@example.com', impersonating: true }),
      },
    ])

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('user')).toHaveTextContent('admin@example.com')
    expect(screen.getByTestId('impersonating')).toHaveTextContent('true')
  })

  it('clears state when /auth/me is unauthorized', async () => {
    mockFetch([{ path: '/api/v1/auth/me', status: 401, body: { detail: 'Not authenticated' } }])

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('user')).toHaveTextContent('none')
    expect(screen.getByTestId('impersonating')).toHaveTextContent('false')
  })

  it('login posts credentials and sets the user', async () => {
    const fetchMock = mockFetch([
      { path: '/api/v1/auth/me', status: 401, body: { detail: 'x' } },
      { path: '/api/v1/auth/login', method: 'POST', body: makeUser({ email: 'a@example.com' }) },
    ])
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))

    await userEvent.click(screen.getByText('login'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/login',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('logout clears the user', async () => {
    mockFetch([
      { path: '/api/v1/auth/me', body: makeMe({ email: 'a@example.com' }) },
      { path: '/api/v1/auth/logout', method: 'POST', status: 204 },
    ])
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))

    await userEvent.click(screen.getByText('logout'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('none'))
  })

  it('refresh re-fetches the current user', async () => {
    let meBody = makeMe({ email: 'first@example.com' })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/auth/me')) return jsonResponse(200, meBody)
      return jsonResponse(404, {})
    })
    vi.stubGlobal('fetch', fetchMock)
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('first@example.com'))

    meBody = makeMe({ email: 'second@example.com' })
    await userEvent.click(screen.getByText('refresh'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('second@example.com'))
  })
})
