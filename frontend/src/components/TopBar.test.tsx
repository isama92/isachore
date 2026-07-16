import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TopBar from './TopBar'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

// Radix menus set pointer-events:none on the body while open; disable the check.
const setup = () => userEvent.setup({ pointerEventsCheck: 0 })

async function openMenu(user: ReturnType<typeof setup>) {
  await user.click(screen.getByRole('button', { name: 'Open user menu' }))
  return within(await screen.findByRole('menu'))
}

describe('TopBar', () => {
  it('renders nothing without a user', () => {
    const { container } = renderWithProviders(<TopBar />, { authValue: { user: null } })
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the initials fallback when the user has no avatar', () => {
    renderWithProviders(<TopBar />, {
      authValue: { user: makeUser({ first_name: 'Ada', last_name: 'Lovelace', avatar_url: null }) },
    })
    expect(screen.getByText('AL')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('renders the avatar image when the user has one', async () => {
    // Radix's loading probe reads image.complete && image.naturalWidth right
    // after setting src; jsdom's Image never "completes", so stub one that
    // reports loaded synchronously.
    class MockImage {
      complete = true
      naturalWidth = 1
      crossOrigin: string | null = null
      referrerPolicy = ''
      src = ''
      addEventListener() {}
      removeEventListener() {}
    }
    vi.stubGlobal('Image', MockImage)

    renderWithProviders(<TopBar />, {
      authValue: {
        user: makeUser({
          first_name: 'Ada',
          last_name: 'Lovelace',
          avatar_url: '/api/v1/media/avatars/x.webp',
        }),
      },
    })
    const img = await screen.findByRole('img')
    expect(img).toHaveAttribute('src', '/api/v1/media/avatars/x.webp')
    expect(img).toHaveAttribute('alt', 'Ada Lovelace')
  })

  it('shows name, email, Profile and a destructive Log out in the menu', async () => {
    const user = setup()
    renderWithProviders(<TopBar />, {
      authValue: {
        user: makeUser({ first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' }),
      },
    })
    const menu = await openMenu(user)

    expect(menu.getByText('Ada Lovelace')).toBeInTheDocument()
    expect(menu.getByText('ada@example.com')).toBeInTheDocument()
    expect(menu.getByRole('menuitem', { name: 'Profile' })).toBeInTheDocument()
    expect(menu.getByRole('menuitem', { name: 'Log out' })).toHaveAttribute(
      'data-variant',
      'destructive',
    )
  })

  it('shows the Admin item only for an admin and logs out', async () => {
    const user = setup()
    const { value } = renderWithProviders(<TopBar />, {
      authValue: { user: makeUser({ is_admin: true }) },
    })
    const menu = await openMenu(user)
    expect(menu.getByRole('menuitem', { name: 'Admin' })).toBeInTheDocument()

    await user.click(menu.getByRole('menuitem', { name: 'Log out' }))
    expect(value.logout).toHaveBeenCalled()
  })

  it('hides the Admin item for a member', async () => {
    const user = setup()
    renderWithProviders(<TopBar />, { authValue: { user: makeUser({ is_admin: false }) } })
    const menu = await openMenu(user)
    expect(menu.queryByRole('menuitem', { name: 'Admin' })).not.toBeInTheDocument()
  })

  it('toggles the colour theme', async () => {
    renderWithProviders(<TopBar />, { authValue: { user: makeUser() } })
    expect(document.documentElement).not.toHaveClass('dark')

    await userEvent.click(screen.getByRole('button', { name: 'Toggle theme' }))
    expect(document.documentElement).toHaveClass('dark')
  })

  it('shows the chores link for any user', () => {
    renderWithProviders(<TopBar />, { authValue: { user: makeUser({ is_admin: false }) } })
    expect(screen.getByRole('link', { name: 'Chores' })).toHaveAttribute('href', '/chores')
  })

  it('returns to the admin session when impersonating', async () => {
    const fetchMock = mockFetch([
      { path: '/api/v1/auth/stop-impersonating', method: 'POST', body: makeUser() },
    ])
    const { value } = renderWithProviders(<TopBar />, {
      authValue: {
        user: makeUser({ first_name: 'Bob', last_name: 'Member' }),
        impersonating: true,
      },
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
    // and refresh() runs so RequireAuth can redirect to login (L5).
    mockFetch([
      {
        path: '/api/v1/auth/stop-impersonating',
        method: 'POST',
        status: 401,
        body: { detail: 'Your admin session has expired. Please log in again.' },
      },
    ])
    const { value } = renderWithProviders(<TopBar />, {
      authValue: {
        user: makeUser({ first_name: 'Bob', last_name: 'Member' }),
        impersonating: true,
      },
    })

    await userEvent.click(screen.getByRole('button', { name: 'Return to admin' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
  })
})
