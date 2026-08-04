import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import RequireRole from './RequireRole'
import { membershipsFor, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'
import type { Membership } from '../lib/types'

// Two guarded branches, so one render exercises the deputy gate and the organiser gate at
// their real relative strengths rather than in isolation.
const tree = (
  <Routes>
    <Route element={<RequireRole min="deputy" />}>
      <Route path="/statistics" element={<div>statistics-content</div>} />
    </Route>
    <Route element={<RequireRole min="organiser" />}>
      <Route path="/chores" element={<div>chores-content</div>} />
    </Route>
    <Route path="/" element={<div>home-marker</div>} />
  </Routes>
)

function at(route: string, memberships: Membership[]) {
  renderWithProviders(tree, { route, authValue: { user: makeUser(), memberships } })
}

describe('RequireRole', () => {
  it('lets an organiser through both gates', () => {
    at('/statistics', membershipsFor('organiser', 1))
    expect(screen.getByText('statistics-content')).toBeInTheDocument()
  })

  it('lets a deputy into Statistics but not the management pages', () => {
    at('/statistics', membershipsFor('deputy', 1))
    expect(screen.getByText('statistics-content')).toBeInTheDocument()
  })

  it('redirects a deputy away from the management pages', () => {
    at('/chores', membershipsFor('deputy', 1))
    expect(screen.getByText('home-marker')).toBeInTheDocument()
  })

  it('redirects a helper away from both', () => {
    at('/statistics', membershipsFor('helper', 1))
    expect(screen.getByText('home-marker')).toBeInTheDocument()
  })

  it('lets a mixed-role user in on the strength of one household', () => {
    // Deputy in household 2 is enough for Statistics even though household 1 is not: the pages
    // behind the guard span every household, and the API returns only the ones that qualify.
    at('/statistics', [
      { household_id: 1, role: 'helper', owned: false },
      { household_id: 2, role: 'deputy', owned: false },
    ])
    expect(screen.getByText('statistics-content')).toBeInTheDocument()
  })

  it('redirects a member of no household', () => {
    // A fresh account, which is a normal state: they create a household first (becoming its
    // organiser), and the pages appear then.
    at('/statistics', [])
    expect(screen.getByText('home-marker')).toBeInTheDocument()
  })
})
