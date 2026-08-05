import { describe, expect, it, vi } from 'vitest'
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

  it('saves a language choice via the language select and applies it', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = mockFetch([{ path: '/api/v1/profile', method: 'PATCH', body: makeUser() }])
    const { value } = renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await user.click(screen.getByRole('combobox', { name: 'Language' }))
    const listbox = within(await screen.findByRole('listbox'))
    await user.click(listbox.getByRole('option', { name: 'Italiano' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ language: 'it' }),
      }),
    )
    // The languageChanged listener mirrors the choice onto <html lang> and the
    // page re-renders in Italian.
    expect(document.documentElement.lang).toBe('it')
    expect(screen.getByRole('heading', { name: 'Il tuo profilo' })).toBeInTheDocument()
  })

  it('rolls back and shows an inline error when the language save fails', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    mockFetch([{ path: '/api/v1/profile', method: 'PATCH', status: 400, body: { detail: 'Nope' } }])
    renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    await user.click(screen.getByRole('combobox', { name: 'Language' }))
    const listbox = within(await screen.findByRole('listbox'))
    await user.click(listbox.getByRole('option', { name: 'Italiano' }))

    expect(await screen.findByText('Nope')).toBeInTheDocument()
    // Optimistic switch rolled back to English.
    await waitFor(() => expect(document.documentElement.lang).toBe('en'))
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

  it('rejects a photo over the size cap without uploading it, and recovers', async () => {
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
    const huge = new File(['x'], 'huge.png', { type: 'image/png' })
    // Fake the size rather than allocating 6 MB of jsdom heap per run.
    Object.defineProperty(huge, 'size', { value: 6 * 1024 * 1024 })
    await userEvent.upload(input, huge)

    expect(
      await screen.findByText('That photo is larger than 5 MB. Pick a smaller one.'),
    ).toBeInTheDocument()
    // The point of the client-side check: nothing was sent.
    expect(fetchMock).not.toHaveBeenCalled()

    // Picking a valid one must still work, which pins the two orderings that make
    // this handler fragile: returning before setAvatarBusy(true) (or the button
    // sticks on "Working…" for good) and clearing the error before the size check
    // (or the rejection message outlives it).
    await userEvent.upload(input, new File(['ok'], 'small.png', { type: 'image/png' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(
      screen.queryByText('That photo is larger than 5 MB. Pick a smaller one.'),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change photo' })).toBeEnabled()
  })

  it('translates a 413 from the server rather than echoing its English detail', async () => {
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

    // No figure in this one: the server's cap is env-tunable, so quoting 5 MB
    // here could be a lie. See AVATAR_MAX_MB in Profile.tsx.
    expect(
      await screen.findByText('That photo is too large. Pick a smaller one.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Image is too large')).not.toBeInTheDocument()
  })

  it('translates a 413 whose body is not JSON (nginx rejecting the body itself)', async () => {
    // Past client_max_body_size nginx answers with its own HTML page, so the api
    // wrapper has no `detail` and ApiError carries the bare status text. The
    // backend never sees the request, which is why this cannot happen in dev.
    const nginx413 = {
      ok: false,
      status: 413,
      statusText: 'Request Entity Too Large',
      json: async () => {
        throw new Error('not json')
      },
    } as unknown as Response
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(nginx413))
    const { container } = renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ avatar_url: null }) },
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, new File(['x'], 'big.png', { type: 'image/png' }))

    expect(
      await screen.findByText('That photo is too large. Pick a smaller one.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Request Entity Too Large')).not.toBeInTheDocument()
  })

  it('still shows the server detail for a non-413 upload failure', async () => {
    mockFetch([
      {
        path: '/api/v1/profile/avatar',
        method: 'PUT',
        status: 400,
        body: { detail: 'That file is not a valid image' },
      },
    ])
    const { container } = renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ avatar_url: null }) },
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, new File(['x'], 'notes.png', { type: 'image/png' }))

    expect(await screen.findByText('That file is not a valid image')).toBeInTheDocument()
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

describe('Profile personal data', () => {
  it('shows the email address, read-only', () => {
    renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ email: 'jo@example.com' }) },
    })

    expect(screen.getByText('jo@example.com')).toBeInTheDocument()
    // Read-only: there is no field to type into, unlike the name beside it.
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
  })

  it('says nothing about confirmation when the server does not ask for it', () => {
    // A null `confirmed_at` means nothing was ever asked of this person, so a badge either
    // way would be reporting on a process that does not run on this deployment.
    renderWithProviders(<Profile />, {
      authValue: {
        user: makeUser({ confirmed_at: null }),
        emailConfirmationRequired: false,
      },
    })

    expect(screen.queryByText('Confirmed')).not.toBeInTheDocument()
    expect(screen.queryByText('Not confirmed')).not.toBeInTheDocument()
  })

  it('marks a confirmed address', () => {
    renderWithProviders(<Profile />, {
      authValue: {
        user: makeUser({ confirmed_at: '2026-07-25T13:06:32Z' }),
        emailConfirmationRequired: true,
      },
    })

    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    expect(screen.queryByText('Not confirmed')).not.toBeInTheDocument()
  })

  it('marks an unconfirmed address', () => {
    renderWithProviders(<Profile />, {
      authValue: {
        user: makeUser({ confirmed_at: null }),
        emailConfirmationRequired: true,
      },
    })

    expect(screen.getByText('Not confirmed')).toBeInTheDocument()
    expect(screen.queryByText('Confirmed')).not.toBeInTheDocument()
  })

  it('uses the accent for confirmed and the danger colour for unconfirmed', () => {
    // Two states have to be told apart at a glance, so the variant carries meaning here
    // rather than only decoration - hence asserting it rather than just the text.
    const { unmount } = renderWithProviders(<Profile />, {
      authValue: {
        user: makeUser({ confirmed_at: '2026-07-25T13:06:32Z' }),
        emailConfirmationRequired: true,
      },
    })
    expect(screen.getByText('Confirmed')).toHaveAttribute('data-variant', 'default')
    unmount()

    renderWithProviders(<Profile />, {
      authValue: { user: makeUser({ confirmed_at: null }), emailConfirmationRequired: true },
    })
    expect(screen.getByText('Not confirmed')).toHaveAttribute('data-variant', 'destructive')
  })

  it('reaches the section from the side menu', () => {
    renderWithProviders(<Profile />, { authValue: { user: makeUser() } })

    expect(screen.getByRole('button', { name: 'Personal data' })).toBeInTheDocument()
    expect(document.getElementById('personal')).toBeInTheDocument()
  })
})
