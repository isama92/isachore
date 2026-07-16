import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import RequireAdmin from './RequireAdmin'
import { renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

const tree = (
  <Routes>
    <Route element={<RequireAdmin />}>
      <Route path="/admin" element={<div>admin-content</div>} />
    </Route>
    <Route path="/" element={<div>home-marker</div>} />
  </Routes>
)

describe('RequireAdmin', () => {
  it('renders the admin content for an admin', () => {
    renderWithProviders(tree, {
      route: '/admin',
      authValue: { user: makeUser({ is_admin: true }) },
    })
    expect(screen.getByText('admin-content')).toBeInTheDocument()
  })

  it('redirects a member to home', () => {
    renderWithProviders(tree, {
      route: '/admin',
      authValue: { user: makeUser({ is_admin: false }) },
    })
    expect(screen.getByText('home-marker')).toBeInTheDocument()
  })

  it('redirects when there is no user', () => {
    renderWithProviders(tree, { route: '/admin', authValue: { user: null } })
    expect(screen.getByText('home-marker')).toBeInTheDocument()
  })
})
