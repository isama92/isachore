import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Profile from './Profile'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

describe('Profile', () => {
  it('saves a new name via PATCH /profile and refreshes', async () => {
    const fetchMock = mockFetch([
      {
        path: '/api/v1/profile',
        method: 'PATCH',
        body: makeUser({ first_name: 'New', last_name: 'Name' }),
      },
    ])
    const { value } = renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ first_name: 'Old', last_name: 'Name' }) },
    })

    const firstName = screen.getByLabelText('First name')
    await userEvent.clear(firstName)
    await userEvent.type(firstName, 'New')
    await userEvent.click(screen.getByRole('button', { name: 'Save name' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ first_name: 'New', last_name: 'Name' }),
      }),
    )
  })

  it('saves an accent choice via PATCH /profile and applies it', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = mockFetch([{ path: '/api/v1/profile', method: 'PATCH', body: makeUser() }])
    const { value } = renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    // Default flavour is Latte + accent teal; pick the Mauve swatch.
    await user.click(screen.getByRole('button', { name: 'Mauve' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ theme: 'latte', accent_color: 'mauve' }),
      }),
    )
    expect(document.documentElement.dataset.accent).toBe('mauve')
  })

  it('saves a flavour choice via the grouped theme select', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = mockFetch([{ path: '/api/v1/profile', method: 'PATCH', body: makeUser() }])
    const { value } = renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await user.click(screen.getByRole('combobox', { name: 'Theme' }))
    const listbox = within(await screen.findByRole('listbox'))
    await user.click(listbox.getByRole('option', { name: 'Catppuccin Mocha' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ theme: 'mocha', accent_color: 'teal' }),
      }),
    )
    expect(document.documentElement.dataset.theme).toBe('mocha')
  })

  it('rolls back and shows an inline error when the appearance save fails', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    mockFetch([{ path: '/api/v1/profile', method: 'PATCH', status: 400, body: { detail: 'Nope' } }])
    renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await user.click(screen.getByRole('button', { name: 'Mauve' }))

    expect(await screen.findByText('Nope')).toBeInTheDocument()
    // Optimistic accent was rolled back to the default.
    expect(document.documentElement.dataset.accent).toBe('teal')
  })

  it('rejects a password mismatch inline without calling the API', async () => {
    const fetchMock = mockFetch([])
    renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await userEvent.type(screen.getByLabelText('Current password'), 'oldpassword123')
    await userEvent.type(screen.getByLabelText('New password'), 'newpassword456')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'different789')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(screen.getByText('The new passwords do not match')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects a too-short new password inline without calling the API', async () => {
    const fetchMock = mockFetch([])
    renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await userEvent.type(screen.getByLabelText('Current password'), 'oldpassword123')
    await userEvent.type(screen.getByLabelText('New password'), 'short')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('changes the password via PATCH /profile and clears the fields', async () => {
    const fetchMock = mockFetch([{ path: '/api/v1/profile', method: 'PATCH', body: makeUser() }])
    const { value } = renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await userEvent.type(screen.getByLabelText('Current password'), 'oldpassword123')
    await userEvent.type(screen.getByLabelText('New password'), 'newpassword456')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'newpassword456')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          current_password: 'oldpassword123',
          new_password: 'newpassword456',
        }),
      }),
    )
    expect(screen.getByLabelText('Current password')).toHaveValue('')
  })

  it('shows a server error inline when the current password is wrong', async () => {
    mockFetch([
      {
        path: '/api/v1/profile',
        method: 'PATCH',
        status: 400,
        body: { detail: 'Current password is incorrect' },
      },
    ])
    renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await userEvent.type(screen.getByLabelText('Current password'), 'wrongpassword')
    await userEvent.type(screen.getByLabelText('New password'), 'newpassword456')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'newpassword456')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByText('Current password is incorrect')).toBeInTheDocument()
  })

  it('uploads a picture as multipart via PUT /profile/avatar', async () => {
    const fetchMock = mockFetch([
      {
        path: '/api/v1/profile/avatar',
        method: 'PUT',
        body: makeUser({ avatar_url: '/api/v1/media/avatars/x.webp' }),
      },
    ])
    const { container, value } = renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ avatar_url: null }) },
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['fake-bytes'], 'photo.png', { type: 'image/png' })
    await userEvent.upload(input, file)

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile/avatar',
      expect.objectContaining({ method: 'PUT', body: expect.any(FormData) }),
    )
  })

  it('shows an inline error when the upload is rejected', async () => {
    mockFetch([
      {
        path: '/api/v1/profile/avatar',
        method: 'PUT',
        status: 413,
        body: { detail: 'Image is too large' },
      },
    ])
    const { container } = renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ avatar_url: null }) },
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, new File(['x'], 'big.png', { type: 'image/png' }))

    expect(await screen.findByText('Image is too large')).toBeInTheDocument()
  })

  it('removes the picture via DELETE /profile/avatar (only shown with a photo)', async () => {
    const fetchMock = mockFetch([
      { path: '/api/v1/profile/avatar', method: 'DELETE', body: makeUser({ avatar_url: null }) },
    ])
    const { value } = renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ avatar_url: '/api/v1/media/avatars/x.webp' }) },
    })

    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile/avatar',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('hides the Remove button when there is no picture', () => {
    renderWithProviders(<Profile />, { authValue: { user: makeUser({ avatar_url: null }) } })
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
  })
})
