import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router'
import RequireAuth from './RequireAuth'
import { renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

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

  it('renders the protected content and top bar for an authed user', () => {
    renderWithProviders(tree, {
      route: '/protected',
      authValue: { user: makeUser({ name: 'Alex Member' }) },
    })
    expect(screen.getByText('protected-content')).toBeInTheDocument()
    // The top bar renders its user menu (name now lives inside that menu).
    expect(screen.getByRole('button', { name: 'Open user menu' })).toBeInTheDocument()
  })
})
