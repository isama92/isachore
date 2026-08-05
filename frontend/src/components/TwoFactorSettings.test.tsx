import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TwoFactorSettings from './TwoFactorSettings'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

const SETUP_BODY = {
  secret: 'ABCD1234EFGH5678',
  otpauth_uri: 'otpauth://totp/isachore:member@example.com?secret=ABCD1234EFGH5678',
  qr: 'data:image/png;base64,iVBORw0KGgo=',
}

describe('TwoFactorSettings', () => {
  it('shows the disabled state with an Enable button', () => {
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: false }) },
    })
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Enable' })).toBeInTheDocument()
  })

  it('says that single sign-on uses the provider own verification instead', () => {
    // A sign-in through an identity provider deliberately skips this step, so somebody who
    // has just enrolled and then signs in through SSO without being asked for a code would
    // otherwise reasonably read that as a bug. Worded to be true on a server with no
    // provider configured too, since this panel cannot see that setting.
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: true }) },
    })
    expect(
      screen.getByText(/sign-ins through it use that provider's own verification instead/i),
    ).toBeInTheDocument()
  })

  it('shows the enabled state with regenerate and disable actions', () => {
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: true }) },
    })
    expect(screen.getByText('Enabled')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Regenerate recovery codes' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Enable' })).not.toBeInTheDocument()
  })

  it('enables 2FA: fetches setup, confirms a code, then reveals recovery codes', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = mockFetch([
      { path: '/api/v1/profile/2fa/setup', method: 'POST', body: SETUP_BODY },
      {
        path: '/api/v1/profile/2fa/confirm',
        method: 'POST',
        body: { recovery_codes: ['code-one', 'code-two', 'code-three'] },
      },
    ])
    const { value } = renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: false }) },
    })

    await user.click(screen.getByRole('button', { name: 'Enable' }))
    const dialog = within(await screen.findByRole('dialog'))
    // The manual-entry key from the setup response is shown for typing by hand.
    expect(await dialog.findByDisplayValue('ABCD1234EFGH5678')).toBeInTheDocument()

    await user.type(dialog.getByLabelText('Authentication code'), '123456')
    await user.click(dialog.getByRole('button', { name: 'Confirm' }))

    // The dialog switches to the recovery-codes view and the user is refreshed.
    expect(await screen.findByText('code-one')).toBeInTheDocument()
    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile/2fa/confirm',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: '123456' }) }),
    )
  })

  it('shows an inline error when the confirm code is rejected', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    mockFetch([
      { path: '/api/v1/profile/2fa/setup', method: 'POST', body: SETUP_BODY },
      {
        path: '/api/v1/profile/2fa/confirm',
        method: 'POST',
        status: 400,
        body: { detail: 'That code is not valid' },
      },
    ])
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: false }) },
    })

    await user.click(screen.getByRole('button', { name: 'Enable' }))
    const dialog = within(await screen.findByRole('dialog'))
    await dialog.findByDisplayValue('ABCD1234EFGH5678')
    await user.type(dialog.getByLabelText('Authentication code'), '000000')
    await user.click(dialog.getByRole('button', { name: 'Confirm' }))

    expect(await dialog.findByText('That code is not valid')).toBeInTheDocument()
  })

  it('disables 2FA with a code', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = mockFetch([
      {
        path: '/api/v1/profile/2fa/disable',
        method: 'POST',
        body: makeUser({ two_factor_enabled: false }),
      },
    ])
    const { value } = renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: true }) },
    })

    await user.click(screen.getByRole('button', { name: 'Disable' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText('Authentication code'), '654321')
    await user.click(dialog.getByRole('button', { name: 'Disable' }))

    await waitFor(() => expect(value.refresh).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile/2fa/disable',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: '654321' }) }),
    )
  })

  it('shows an inline error when the disable code is rejected', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    mockFetch([
      {
        path: '/api/v1/profile/2fa/disable',
        method: 'POST',
        status: 400,
        body: { detail: 'That code is not valid' },
      },
    ])
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: true }) },
    })

    await user.click(screen.getByRole('button', { name: 'Disable' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText('Authentication code'), '000000')
    await user.click(dialog.getByRole('button', { name: 'Disable' }))

    expect(await dialog.findByText('That code is not valid')).toBeInTheDocument()
  })

  it('shows an error when setup cannot be started', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    mockFetch([
      {
        path: '/api/v1/profile/2fa/setup',
        method: 'POST',
        status: 503,
        body: { detail: 'Two-factor authentication is temporarily unavailable' },
      },
    ])
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: false }) },
    })

    await user.click(screen.getByRole('button', { name: 'Enable' }))
    const dialog = within(await screen.findByRole('dialog'))
    expect(
      await dialog.findByText('Two-factor authentication is temporarily unavailable'),
    ).toBeInTheDocument()
  })

  it('regenerates recovery codes', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    mockFetch([
      {
        path: '/api/v1/profile/2fa/recovery-codes',
        method: 'POST',
        body: { recovery_codes: ['fresh-one', 'fresh-two'] },
      },
    ])
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: true }) },
    })

    await user.click(screen.getByRole('button', { name: 'Regenerate recovery codes' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText('Authentication code'), '111111')
    await user.click(dialog.getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('fresh-one')).toBeInTheDocument()
  })

  it('shows an inline error when regeneration is rejected', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    mockFetch([
      {
        path: '/api/v1/profile/2fa/recovery-codes',
        method: 'POST',
        status: 400,
        body: { detail: 'That code is not valid' },
      },
    ])
    renderWithProviders(<TwoFactorSettings />, {
      authValue: { user: makeUser({ two_factor_enabled: true }) },
    })

    await user.click(screen.getByRole('button', { name: 'Regenerate recovery codes' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText('Authentication code'), '000000')
    await user.click(dialog.getByRole('button', { name: 'Confirm' }))

    expect(await dialog.findByText('That code is not valid')).toBeInTheDocument()
  })
})
