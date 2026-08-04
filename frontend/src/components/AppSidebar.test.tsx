import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import AppSidebar from './AppSidebar'
import { membershipsFor, ownedMemberships, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'
import { SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { AuthContextValue } from '../auth/context'

// AppSidebar reads useSidebar() and renders tooltip'd menu buttons, so it needs
// both providers around it (RequireAuth supplies these in the real app).
const inShell = (ui: ReactElement) => (
  <TooltipProvider>
    <SidebarProvider>{ui}</SidebarProvider>
  </TooltipProvider>
)

function renderSidebar(authValue: Partial<AuthContextValue>, route = '/') {
  return renderWithProviders(inShell(<AppSidebar />), { authValue, route })
}

describe('AppSidebar', () => {
  it('renders no navigation without a user', () => {
    renderSidebar({ user: null })
    expect(screen.queryByRole('link', { name: 'Home' })).not.toBeInTheDocument()
  })

  it('shows the user identity', () => {
    renderSidebar({
      user: makeUser({ first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' }),
    })
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('ada@example.com')).toBeInTheDocument()
  })

  it('renders the brand mark beside the wordmark', () => {
    const { container } = renderSidebar({ user: makeUser() })
    const brand = screen.getByRole('link', { name: 'isachore' })
    expect(brand).toHaveAttribute('href', '/')
    expect(brand).toHaveTextContent('isachore')
    // Just the tiled head here — the handwritten caption belongs to the login page,
    // where there is room for it.
    expect(brand.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(1)
    expect(container.querySelector('.bg-primary.shadow-logo')).toBeInTheDocument()
  })

  it('labels the brand link so it keeps a name when the wordmark is hidden', () => {
    // In icon mode the wordmark is display:none, which also removes it from the
    // accessibility tree; without the label the link would have no name at all.
    renderSidebar({ user: makeUser() })
    expect(screen.getByRole('link', { name: 'isachore' })).toHaveAttribute('aria-label', 'isachore')
  })

  it('renders the core nav items with the right destinations', () => {
    renderSidebar({ user: makeUser() })
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'My Chores' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'Unscheduled Chores' })).toHaveAttribute(
      'href',
      '/unscheduled',
    )
    expect(screen.getByRole('link', { name: 'Chores Management' })).toHaveAttribute(
      'href',
      '/chores',
    )
    expect(screen.getByRole('link', { name: 'History' })).toHaveAttribute('href', '/history')
    expect(screen.getByRole('link', { name: 'Profile' })).toHaveAttribute('href', '/profile')
  })

  it('renders the core nav items in order', () => {
    // The default auth value owns household 1 and organises it, i.e. every item.
    renderSidebar({ user: makeUser() })
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    const labels = screen.getAllByRole('link').filter((el) => nav.contains(el))
    expect(labels.map((el) => el.textContent)).toEqual([
      'My Chores',
      'Unscheduled Chores',
      'History',
      'Statistics',
      'Logs',
      'Tags',
      'Chores Management',
      'Households',
      'Profile',
    ])
  })

  // Household roles decide which items exist at all. The nav is global while roles are
  // per household, so the rule is "reaches the role somewhere" - see the mixed case below.
  function navLabels(): (string | null)[] {
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    return screen
      .getAllByRole('link')
      .filter((el) => nav.contains(el))
      .map((el) => el.textContent)
  }

  it('shows a helper only the pages they can use, History included', () => {
    // History is unconditional: the endpoint narrows per household (their own closures in a
    // household they only help in) rather than refusing, so hiding the item would hide the
    // one place they can undo a mis-skip of their own.
    renderSidebar({ user: makeUser(), memberships: membershipsFor('helper', 1) })
    expect(navLabels()).toEqual([
      'My Chores',
      'Unscheduled Chores',
      'History',
      'Households',
      'Profile',
    ])
  })

  it('adds Statistics for a deputy, but not the management pages', () => {
    // History used to appear at this rung and is now above it; Statistics is what the deputy
    // role still buys.
    renderSidebar({ user: makeUser(), memberships: membershipsFor('deputy', 1) })
    expect(navLabels()).toEqual([
      'My Chores',
      'Unscheduled Chores',
      'History',
      'Statistics',
      'Households',
      'Profile',
    ])
  })

  it('shows a member of no household the minimal nav', () => {
    // Every fresh account starts here (nothing provisions a household). They create one,
    // become its organiser, and the rest appears. History is in the minimal set because it
    // is unconditional; for them it renders its empty state.
    renderSidebar({ user: makeUser(), memberships: [] })
    expect(navLabels()).toEqual([
      'My Chores',
      'Unscheduled Chores',
      'History',
      'Households',
      'Profile',
    ])
  })

  it('hides Logs from an organiser who owns nothing', () => {
    // Ownership is not a rung on the ladder: this user manages the household's chores and
    // still does not get the record of that management. Tags proves the organiser role landed,
    // so the missing Logs is about `owned` rather than about the role being ignored.
    renderSidebar({ user: makeUser(), memberships: membershipsFor('organiser', 1) })
    expect(navLabels()).toContain('Tags')
    expect(navLabels()).not.toContain('Logs')
  })

  it('shows Logs to an owner', () => {
    renderSidebar({ user: makeUser(), memberships: ownedMemberships(1) })
    expect(navLabels()).toContain('Logs')
  })

  it('shows a mixed-role user everything one household grants', () => {
    // Helper in household 1, organiser in 2: the union wins, and the endpoints behind each
    // page then return only household 2's data.
    renderSidebar({
      user: makeUser(),
      memberships: [
        { household_id: 1, role: 'helper', owned: false },
        { household_id: 2, role: 'organiser', owned: false },
      ],
    })
    expect(navLabels()).toContain('Chores Management')
    expect(navLabels()).toContain('Tags')
  })

  it('keeps the Admin group for a site admin who is only a household helper', () => {
    // is_admin is a server-wide flag, orthogonal to household roles: an operator does not
    // lose the admin pages because of what they may do in their own kitchen.
    renderSidebar({
      user: makeUser({ is_admin: true }),
      memberships: membershipsFor('helper', 1),
    })
    expect(screen.getByRole('button', { name: 'Admin' })).toBeInTheDocument()
    expect(navLabels()).not.toContain('Chores Management')
  })

  it('shows the Admin group trigger only for an admin', () => {
    renderSidebar({ user: makeUser({ is_admin: true }) })
    expect(screen.getByRole('button', { name: 'Admin' })).toBeInTheDocument()
  })

  it('hides the Admin group for a member', () => {
    renderSidebar({ user: makeUser({ is_admin: false }) })
    expect(screen.queryByRole('button', { name: 'Admin' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
  })

  it('expands the Admin group to reveal the Users sub-link', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    // At route '/' the group is collapsed, so its children are not rendered.
    renderSidebar({ user: makeUser({ is_admin: true }) })
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Admin' }))
    expect(await screen.findByRole('link', { name: 'Users' })).toHaveAttribute(
      'href',
      '/admin/users',
    )
  })

  it('opens the Admin group and marks Users active on an admin route', () => {
    renderSidebar({ user: makeUser({ is_admin: true }) }, '/admin/users')
    expect(screen.getByRole('link', { name: 'Users' })).toHaveAttribute('data-active', 'true')
  })

  it('marks the active section from the current route', () => {
    renderSidebar({ user: makeUser() }, '/chores')
    expect(screen.getByRole('link', { name: 'Chores Management' })).toHaveAttribute(
      'data-active',
      'true',
    )
    expect(screen.getByRole('link', { name: 'My Chores' })).toHaveAttribute('data-active', 'false')
  })

  it('keeps the Chores section active on its nested routes', () => {
    renderSidebar({ user: makeUser() }, '/chores/new')
    expect(screen.getByRole('link', { name: 'Chores Management' })).toHaveAttribute(
      'data-active',
      'true',
    )
  })

  it('logs out when the Log out button is clicked', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { value } = renderSidebar({ user: makeUser() })
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(value.logout).toHaveBeenCalled()
  })
})
