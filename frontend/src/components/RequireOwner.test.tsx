import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import RequireOwner from './RequireOwner'
import { membershipsFor, ownedMemberships, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'
import type { Membership } from '../lib/types'

const tree = (
  <Routes>
    <Route element={<RequireOwner />}>
      <Route path="/logs" element={<div>logs-content</div>} />
    </Route>
    <Route path="/" element={<div>home-marker</div>} />
  </Routes>
)

function at(memberships: Membership[]) {
  renderWithProviders(tree, { route: '/logs', authValue: { user: makeUser(), memberships } })
}

describe('RequireOwner', () => {
  it('lets a household owner through', () => {
    at(ownedMemberships(1))
    expect(screen.getByText('logs-content')).toBeInTheDocument()
  })

  it('redirects an organiser who owns nothing', () => {
    // The load-bearing case: ownership is not a rung on the role ladder, so the strongest
    // role there is must not open this. Drop `m.owned` from ownsAnyHousehold and only this
    // fails.
    at(membershipsFor('organiser', 1))
    expect(screen.getByText('home-marker')).toBeInTheDocument()
  })

  it('redirects a member of no household', () => {
    // A fresh account, which is a normal state: they create a household, become its owner,
    // and the page appears then.
    at([])
    expect(screen.getByText('home-marker')).toBeInTheDocument()
  })

  it('lets an owner in on the strength of one household', () => {
    // Owner of 2, merely an organiser in 1. The page spans every household and the endpoint
    // returns only the owned ones, so "at least one" is all this guard can decide.
    at([...membershipsFor('organiser', 1), ...ownedMemberships(2)])
    expect(screen.getByText('logs-content')).toBeInTheDocument()
  })
})
