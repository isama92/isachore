import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import RequireAuth from './RequireAuth'
import { makeAuthValue, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'
import { AuthContext } from '../auth/context'
import ThemeProvider from '../theme/ThemeProvider'
import type { User } from '../lib/types'

function LoginMarker() {
  const location = useLocation()
  const state = location.state as { from?: string } | null
  return <div data-testid="login">from:{state?.from ?? 'none'}</div>
}

const tree = (
  <Routes>
    <Route element={<RequireAuth />}>
      <Route path="/protected" element={<div>protected-content</div>} />
    </Route>
    <Route path="/login" element={<LoginMarker />} />
  </Routes>
)

describe('RequireAuth', () => {
  it('renders nothing while auth is loading', () => {
    const { container } = renderWithProviders(tree, {
      route: '/protected',
      authValue: { loading: true },
    })
    expect(container).toBeEmptyDOMElement()
  })

  it('redirects to /login and remembers the origin', () => {
    renderWithProviders(tree, { route: '/protected', authValue: { user: null } })
    expect(screen.getByTestId('login')).toHaveTextContent('from:/protected')
  })

  it('renders the protected content, sidebar and top bar for an authed user', () => {
    renderWithProviders(tree, {
      route: '/protected',
      authValue: { user: makeUser({ first_name: 'Alex', last_name: 'Member' }) },
    })
    expect(screen.getByText('protected-content')).toBeInTheDocument()
    // The slim top bar exposes the sidebar toggle.
    expect(screen.getByRole('button', { name: 'Toggle sidebar' })).toBeInTheDocument()
    // The sidebar shows the identity block and primary nav.
    expect(screen.getByText('Alex Member')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'My Chores' })).toBeInTheDocument()
  })
})

// renderWithProviders freezes its auth value at render time, so an identity change needs a
// harness that owns the value itself. The probe counts mounts, because a mount is what
// re-runs a page's load effect - and re-running those is the whole point of the key.
let mounts = 0

function Probe() {
  useEffect(() => {
    mounts += 1
  }, [])
  return <div>protected-content</div>
}

const OTHER = makeUser({ id: 2, email: 'other@example.com', first_name: 'Other' })

function Harness() {
  const [user, setUser] = useState<User>(makeUser())
  return (
    <ThemeProvider>
      <AuthContext.Provider value={makeAuthValue({ user })}>
        <MemoryRouter initialEntries={['/protected']}>
          <button onClick={() => setUser(OTHER)}>switch identity</button>
          {/* What a profile save does: refresh() hands back the same account in a new
              object, so `user` changes identity while `user.id` does not. */}
          <button onClick={() => setUser((u) => ({ ...u }))}>refresh same user</button>
          <Routes>
            <Route element={<RequireAuth />}>
              <Route path="/protected" element={<Probe />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </ThemeProvider>
  )
}

describe('RequireAuth remounting', () => {
  beforeEach(() => {
    mounts = 0
  })

  it('remounts the page when the signed-in account changes', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<Harness />)
    expect(mounts).toBe(1)

    await user.click(screen.getByRole('button', { name: 'switch identity' }))

    // Without the key on <Outlet> the page stays mounted and keeps whatever it fetched
    // as the previous account - the impersonation bug this exists to prevent.
    expect(mounts).toBe(2)
    expect(screen.getByText('protected-content')).toBeInTheDocument()
  })

  it('does not remount when the same account is refreshed', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<Harness />)
    expect(mounts).toBe(1)

    await user.click(screen.getByRole('button', { name: 'refresh same user' }))

    // Keying on the user object rather than its id would throw the page away on every
    // profile save, losing scroll position, open dialogs and half-typed filters.
    expect(mounts).toBe(1)
  })
})
