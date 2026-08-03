import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import AuthProvider from './AuthProvider'
import { useAuth } from './useAuth'
import { api } from '../lib/api'
import ThemeProvider from '../theme/ThemeProvider'
import i18n from '../i18n/i18n'
import { jsonResponse, mockFetch } from '../test/utils'
import { makeMe } from '../test/fixtures'

function Harness() {
  const { user, impersonating, memberships, loading, login, verifyTwoFactor, logout, refresh } =
    useAuth()
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user ? user.email : 'none'}</span>
      <span data-testid="impersonating">{String(impersonating)}</span>
      <span data-testid="memberships">
        {memberships.map((m) => `${m.household_id}:${m.role}`).join(',') || 'none'}
      </span>
      <button onClick={() => void login('a@example.com', 'password12345', true)}>login</button>
      <button onClick={() => void verifyTwoFactor('123456')}>verify</button>
      <button onClick={() => void logout()}>logout</button>
      <button onClick={() => void refresh()}>refresh</button>
      <button onClick={() => void api.get('/api/v1/thing').catch(() => {})}>fetch</button>
    </div>
  )
}

function renderProvider() {
  // AuthProvider reads useTheme() to sync saved appearance, so it needs a
  // ThemeProvider ancestor (matches the real tree in main.tsx).
  return render(
    <ThemeProvider>
      <AuthProvider>
        <Harness />
      </AuthProvider>
    </ThemeProvider>,
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
      {
        path: '/api/v1/auth/login',
        method: 'POST',
        body: { two_factor_required: false, user: makeMe({ email: 'a@example.com' }) },
      },
    ])
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))

    await userEvent.click(screen.getByText('login'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/login',
      expect.objectContaining({
        method: 'POST',
        // The remember flag is threaded straight into the request body
        body: JSON.stringify({
          email: 'a@example.com',
          password: 'password12345',
          remember: true,
        }),
      }),
    )
  })

  it('a 2FA-required login does not sign in until the code is verified', async () => {
    mockFetch([
      { path: '/api/v1/auth/me', status: 401, body: { detail: 'x' } },
      {
        path: '/api/v1/auth/login',
        method: 'POST',
        body: { two_factor_required: true, user: null },
      },
      {
        path: '/api/v1/auth/verify-2fa',
        method: 'POST',
        body: makeMe({ email: 'a@example.com' }),
      },
    ])
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))

    // Password step succeeds but 2FA is required, so no user yet.
    await userEvent.click(screen.getByText('login'))
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('user')).toHaveTextContent('none')

    // Verifying the code completes the login.
    await userEvent.click(screen.getByText('verify'))
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))
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

  it('logout forgets remembered table settings, but not the browser preferences', async () => {
    mockFetch([
      { path: '/api/v1/auth/me', body: makeMe({ email: 'a@example.com' }) },
      { path: '/api/v1/auth/logout', method: 'POST', status: 204 },
    ])
    // Saved table filters name colleagues and households, and the admin tables save
    // name/email search terms, so on a shared device the next account must not
    // inherit them.
    localStorage.setItem('isachore-table-history', '{"filters":{"user_id":"7"}}')
    localStorage.setItem('isachore-table-admin-users', '{"filters":{"email":"someone@x.com"}}')
    localStorage.setItem('isachore-language', 'it')
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))

    await userEvent.click(screen.getByText('logout'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('none'))
    expect(localStorage.getItem('isachore-table-history')).toBeNull()
    expect(localStorage.getItem('isachore-table-admin-users')).toBeNull()
    // The owner goes too, so a logout really does leave nothing behind.
    expect(localStorage.getItem('isachore-tables-owner')).toBeNull()
    expect(localStorage.getItem('isachore-language')).toBe('it')
  })

  it('forgets table settings it cannot attribute when a session resumes', async () => {
    // Settings with no recorded owner cannot be shown to belong to whoever is signing
    // in, so they are dropped. This is also the upgrade path: anyone already logged in
    // when the owner key shipped has settings from before it existed, and they are
    // swept on the next page load rather than lingering unattributed until a login.
    mockFetch([{ path: '/api/v1/auth/me', body: makeMe({ id: 7, email: 'a@example.com' }) }])
    localStorage.setItem('isachore-table-admin-users', '{"filters":{"email":"someone@x.com"}}')
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))
    expect(localStorage.getItem('isachore-table-admin-users')).toBeNull()
    expect(localStorage.getItem('isachore-tables-owner')).toBe('7')
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

  it('adopts the server flavour + accent + language from /auth/me', async () => {
    mockFetch([
      {
        path: '/api/v1/auth/me',
        body: makeMe({
          email: 'ada@example.com',
          theme: 'frappe',
          accent_color: 'mauve',
          language: 'it',
        }),
      },
    ])
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('ada@example.com'))
    expect(document.documentElement.dataset.theme).toBe('frappe')
    expect(document.documentElement.dataset.accent).toBe('mauve')
    expect(localStorage.getItem('isachore-theme')).toBe('frappe')
    expect(localStorage.getItem('isachore-accent')).toBe('mauve')
    await waitFor(() => expect(i18n.language).toBe('it'))
    expect(localStorage.getItem('isachore-language')).toBe('it')
  })

  it('does not adopt or persist the theme or language while impersonating', async () => {
    mockFetch([
      {
        path: '/api/v1/auth/me',
        body: makeMe({
          email: 'ada@example.com',
          theme: 'frappe',
          accent_color: 'mauve',
          language: 'it',
          impersonating: true,
        }),
      },
    ])
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('ada@example.com'))
    // Stays on the OS default (Latte) and English; the admin's own choices are
    // left untouched.
    expect(document.documentElement.dataset.theme).toBe('latte')
    expect(localStorage.getItem('isachore-theme')).toBeNull()
    expect(localStorage.getItem('isachore-accent')).toBeNull()
    expect(i18n.language).toBe('en')
    expect(localStorage.getItem('isachore-language')).toBeNull()
  })

  it('clears auth state and toasts when an API call 401s mid-session', async () => {
    const toastSpy = vi.spyOn(toast, 'info')
    mockFetch([
      { path: '/api/v1/auth/me', body: makeMe({ email: 'a@example.com', impersonating: true }) },
      { path: '/api/v1/thing', status: 401, body: { detail: 'Session expired' } },
    ])
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))
    expect(screen.getByTestId('impersonating')).toHaveTextContent('true')

    // A data call whose session has expired mid-use returns 401.
    await userEvent.click(screen.getByText('fetch'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('none'))
    expect(screen.getByTestId('impersonating')).toHaveTextContent('false')
    expect(toastSpy).toHaveBeenCalledWith('Your session has expired. Please sign in again.', {
      id: 'session-expired',
    })
  })

  it('forgets remembered table settings when the session expires mid-use', async () => {
    mockFetch([
      { path: '/api/v1/auth/me', body: makeMe({ email: 'a@example.com' }) },
      { path: '/api/v1/thing', status: 401, body: { detail: 'Session expired' } },
    ])
    localStorage.setItem('isachore-table-admin-users', '{"filters":{"email":"someone@x.com"}}')
    localStorage.setItem('isachore-language', 'it')
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))

    await userEvent.click(screen.getByText('fetch'))

    // An expiry takes no action from the user, so on a shared device it is the
    // likeliest way a session ends: it has to clear the same things logout does.
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('none'))
    expect(localStorage.getItem('isachore-table-admin-users')).toBeNull()
    expect(localStorage.getItem('isachore-language')).toBe('it')
  })

  it('forgets remembered table settings when the account behind the session changes', async () => {
    // Impersonation starting or stopping both land in refresh(), reporting a
    // different user id.
    let meBody = makeMe({ id: 1, email: 'admin@example.com' })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/auth/me')) return jsonResponse(200, meBody)
      return jsonResponse(404, {})
    })
    vi.stubGlobal('fetch', fetchMock)
    localStorage.setItem('isachore-table-chores', '{"filters":{"household_id":"4"}}')
    localStorage.setItem('isachore-tables-owner', '1')
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('admin@example.com'))
    expect(localStorage.getItem('isachore-table-chores')).not.toBeNull()

    meBody = makeMe({ id: 2, email: 'other@example.com', impersonating: true })
    await userEvent.click(screen.getByText('refresh'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('other@example.com'))
    expect(localStorage.getItem('isachore-table-chores')).toBeNull()
  })

  it('forgets remembered table settings when a different account logs in after a cold boot', async () => {
    // The "walked away from the machine" path: A closed the tab without logging out,
    // so neither logout nor handleExpiry ran, and by the time A's cookie has expired
    // there is no previous user in memory to compare against. Whoever logs in next
    // must still not inherit A's search terms, which are the one stored value that
    // nothing prunes.
    mockFetch([
      { path: '/api/v1/auth/me', status: 401, body: { detail: 'Not authenticated' } },
      {
        path: '/api/v1/auth/login',
        method: 'POST',
        body: { two_factor_required: false, user: makeMe({ id: 99, email: 'b@example.com' }) },
      },
    ])
    localStorage.setItem('isachore-table-admin-users', '{"filters":{"email":"someone@x.com"}}')
    localStorage.setItem('isachore-tables-owner', '7')
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))

    await userEvent.click(screen.getByText('login'))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('b@example.com'))
    expect(localStorage.getItem('isachore-table-admin-users')).toBeNull()
    expect(localStorage.getItem('isachore-tables-owner')).toBe('99')
  })

  it('keeps remembered table settings across a cold boot for the same account', async () => {
    // The flip side: reopening the browser on your own still-valid session must not
    // cost you your settings.
    mockFetch([{ path: '/api/v1/auth/me', body: makeMe({ id: 7, email: 'a@example.com' }) }])
    localStorage.setItem('isachore-table-chores', '{"filters":{"household_id":"4"}}')
    localStorage.setItem('isachore-tables-owner', '7')
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))
    expect(localStorage.getItem('isachore-table-chores')).not.toBeNull()
  })

  it('keeps remembered table settings across a same-account refresh', async () => {
    // Every profile save refreshes, so this must not be a clear.
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/auth/me')) {
        return jsonResponse(200, makeMe({ id: 1, email: 'a@example.com' }))
      }
      return jsonResponse(404, {})
    })
    vi.stubGlobal('fetch', fetchMock)
    localStorage.setItem('isachore-table-chores', '{"filters":{"household_id":"4"}}')
    localStorage.setItem('isachore-tables-owner', '1')
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))

    await userEvent.click(screen.getByText('refresh'))

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1))
    expect(localStorage.getItem('isachore-table-chores')).not.toBeNull()
  })

  it('ignores a 401 when there is no active session (pre-auth)', async () => {
    const toastSpy = vi.spyOn(toast, 'info')
    const fetchMock = mockFetch([
      { path: '/api/v1/auth/me', status: 401, body: { detail: 'x' } },
      { path: '/api/v1/thing', status: 401, body: { detail: 'x' } },
    ])
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('user')).toHaveTextContent('none')

    await userEvent.click(screen.getByText('fetch'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/thing', expect.anything()))

    // The gate short-circuits: no user, so no toast and no spurious redirect.
    expect(screen.getByTestId('user')).toHaveTextContent('none')
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('unregisters the expiry handler on unmount', async () => {
    const toastSpy = vi.spyOn(toast, 'info')
    mockFetch([{ path: '/api/v1/auth/me', body: makeMe({ email: 'a@example.com' }) }])
    const { unmount } = renderProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('a@example.com'))

    unmount()

    // After unmount the handler is gone, so a later 401 just throws with nothing
    // reacting to it.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'x' })))
    await expect(api.get('/api/v1/thing')).rejects.toMatchObject({ status: 401 })
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('adopts the household roles from /auth/me, and drops them on logout', async () => {
    // The sidebar reads these, so a session that carries a user but no roles renders the
    // minimal nav - and a logout that leaves them behind would light it up for nobody.
    mockFetch([
      {
        path: '/api/v1/auth/me',
        body: makeMe({
          email: 'a@example.com',
          memberships: [
            { household_id: 1, role: 'organiser' },
            { household_id: 2, role: 'helper' },
          ],
        }),
      },
      { path: '/api/v1/auth/logout', method: 'POST', status: 204 },
    ])
    renderProvider()

    await waitFor(() =>
      expect(screen.getByTestId('memberships')).toHaveTextContent('1:organiser,2:helper'),
    )

    await userEvent.click(screen.getByText('logout'))
    await waitFor(() => expect(screen.getByTestId('memberships')).toHaveTextContent('none'))
  })

  it('takes the roles from the login response, without a second /auth/me', async () => {
    // Login sets the auth state directly, so if the roles did not ride along the first
    // screen after signing in would show the minimal nav until the next reload.
    const fetchMock = mockFetch([
      { path: '/api/v1/auth/me', status: 401, body: { detail: 'Not authenticated' } },
      {
        path: '/api/v1/auth/login',
        method: 'POST',
        body: {
          two_factor_required: false,
          user: makeMe({
            email: 'a@example.com',
            memberships: [{ household_id: 3, role: 'deputy' }],
          }),
        },
      },
    ])
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    const meCallsBefore = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes('/auth/me'),
    ).length

    await userEvent.click(screen.getByText('login'))

    await waitFor(() => expect(screen.getByTestId('memberships')).toHaveTextContent('3:deputy'))
    const meCallsAfter = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes('/auth/me'),
    ).length
    expect(meCallsAfter).toBe(meCallsBefore)
  })
})
