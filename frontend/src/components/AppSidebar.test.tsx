import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import AppSidebar from './AppSidebar'
import { renderWithProviders } from '../test/utils'
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
    expect(screen.getByRole('link', { name: 'Your Chores' })).toHaveAttribute('href', '/')
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
    renderSidebar({ user: makeUser() })
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    const labels = screen.getAllByRole('link').filter((el) => nav.contains(el))
    expect(labels.map((el) => el.textContent)).toEqual([
      'Your Chores',
      'Unscheduled Chores',
      'History',
      'Statistics',
      'Tags',
      'Chores Management',
      'Households',
      'Profile',
    ])
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
    expect(screen.getByRole('link', { name: 'Your Chores' })).toHaveAttribute(
      'data-active',
      'false',
    )
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
