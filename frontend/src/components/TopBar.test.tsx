import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TopBar from './TopBar'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

describe('TopBar', () => {
  it('renders nothing without a user', () => {
    const { container } = renderWithProviders(<TopBar />, { authValue: { user: null } })
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the admin link and name for an admin and logs out', async () => {
    const { value } = renderWithProviders(<TopBar />, {
      authValue: { user: makeUser({ name: 'Admin User', is_admin: true }) },
    })
    expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument()
    expect(screen.getByText('Admin User')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(value.logout).toHaveBeenCalled()
  })

  it('hides the admin link for a member', () => {
    renderWithProviders(<TopBar />, { authValue: { user: makeUser({ is_admin: false }) } })
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
  })

  it('returns to the admin session when impersonating', async () => {
    const fetchMock = mockFetch([
      { path: '/api/v1/auth/stop-impersonating', method: 'POST', body: makeUser() },
    ])
    const { value } = renderWithProviders(<TopBar />, {
      authValue: { user: makeUser({ name: 'Bob Member' }), impersonating: true },
    })

    await userEvent.click(screen.getByRole('button', { name: 'Return to admin' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/stop-impersonating',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
