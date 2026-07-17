import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import TopBar from './TopBar'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'
import { SidebarProvider } from '@/components/ui/sidebar'
import type { AuthContextValue } from '../auth/context'

// TopBar reads useSidebar(), so it must render inside a SidebarProvider.
const inShell = (ui: ReactElement) => <SidebarProvider>{ui}</SidebarProvider>

function renderTopBar(authValue: Partial<AuthContextValue>) {
  return renderWithProviders(inShell(<TopBar />), { authValue })
}

describe('TopBar', () => {
  it('renders no header controls without a user', () => {
    renderTopBar({ user: null })
    expect(screen.queryByRole('button', { name: 'Toggle sidebar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Return to admin' })).not.toBeInTheDocument()
  })

  it('renders the sidebar toggle for an authed user', () => {
    renderTopBar({ user: makeUser() })
    expect(screen.getByRole('button', { name: 'Toggle sidebar' })).toBeInTheDocument()
  })

  it('does not show the return-to-admin button when not impersonating', () => {
    renderTopBar({ user: makeUser(), impersonating: false })
    expect(screen.queryByRole('button', { name: 'Return to admin' })).not.toBeInTheDocument()
  })

  it('returns to the admin session when impersonating', async () => {
    const fetchMock = mockFetch([
      { path: '/api/v1/auth/stop-impersonating', method: 'POST', body: makeUser() },
    ])
    const { value } = renderTopBar({
      user: makeUser({ first_name: 'Bob', last_name: 'Member' }),
      impersonating: true,
    })

    await userEvent.click(screen.getByRole('button', { name: 'Return to admin' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/stop-impersonating',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('still refreshes when the admin session has expired (401)', async () => {
    // The server ends both sessions and returns 401; the button must not throw,
    // and refresh() runs so RequireAuth can redirect to login.
    mockFetch([
      {
        path: '/api/v1/auth/stop-impersonating',
        method: 'POST',
        status: 401,
        body: { detail: 'Your admin session has expired. Please log in again.' },
      },
    ])
    const { value } = renderTopBar({
      user: makeUser({ first_name: 'Bob', last_name: 'Member' }),
      impersonating: true,
    })

    await userEvent.click(screen.getByRole('button', { name: 'Return to admin' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
  })
})
