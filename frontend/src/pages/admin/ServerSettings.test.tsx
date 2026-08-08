import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import ServerSettings from './ServerSettings'
import { renderWithProviders } from '../../test/utils'
import { makeServerSettings, makeUser } from '../../test/fixtures'
import type { ServerSettings as ServerSettingsData } from '../../lib/types'

const admin = makeUser({ id: 1, email: 'admin@example.com', is_admin: true })

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

type FetchMock = ReturnType<typeof vi.fn>

function stubFetch(opts: {
  settings: ServerSettingsData
  patch?: () => Response
  post?: () => Response
}): FetchMock {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET') return jsonBody(opts.settings)
    if (method === 'PATCH' && opts.patch) return opts.patch()
    if (method === 'POST' && opts.post) return opts.post()
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('ServerSettings', () => {
  it('enables confirmation when SMTP is configured', async () => {
    const fetchMock = stubFetch({
      settings: makeServerSettings({ require_confirmation: false, smtp_configured: true }),
      patch: () =>
        jsonBody(makeServerSettings({ require_confirmation: true, smtp_configured: true })),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    const checkbox = await screen.findByRole('checkbox', { name: 'Require email confirmation' })
    expect(checkbox).not.toBeChecked()
    await user.click(checkbox)

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/admin/settings',
        expect.objectContaining({ method: 'PATCH' }),
      ),
    )
    expect(toastSpy).toHaveBeenCalledWith('Settings saved')
    await waitFor(() => expect(checkbox).toBeChecked())
  })

  it('rolls back and shows the error when enabling without SMTP', async () => {
    stubFetch({
      settings: makeServerSettings({ require_confirmation: false, smtp_configured: false }),
      patch: () => jsonBody({ detail: 'There is no confirmation SMTP server configured' }, 400),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    const checkbox = await screen.findByRole('checkbox', { name: 'Require email confirmation' })
    await user.click(checkbox)

    expect(
      await screen.findByText('There is no confirmation SMTP server configured'),
    ).toBeInTheDocument()
    await waitFor(() => expect(checkbox).not.toBeChecked())
  })

  it('shows the not-configured note and disables the test button without SMTP', async () => {
    stubFetch({ settings: makeServerSettings({ smtp_configured: false }) })
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    expect(await screen.findByText(/No SMTP server is configured/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('sends a test email', async () => {
    const fetchMock = stubFetch({
      settings: makeServerSettings({ smtp_configured: true }),
      post: () => jsonBody(undefined, 204),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    await user.click(await screen.findByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/admin/settings/test-email',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(toastSpy).toHaveBeenCalledWith('Test email sent to admin@example.com')
  })

  it('blocks the send button with a countdown once used', async () => {
    const fetchMock = stubFetch({
      settings: makeServerSettings({ smtp_configured: true }),
      post: () => jsonBody(undefined, 204),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    await user.click(await screen.findByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/admin/settings/test-email',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    // After sending, the button counts down and can't be clicked again.
    const cooling = await screen.findByRole('button', { name: /Wait \d+s/ })
    expect(cooling).toBeDisabled()
  })

  it('shows a cooldown note when the server returns 429', async () => {
    stubFetch({
      settings: makeServerSettings({ smtp_configured: true }),
      post: () => jsonBody({ detail: 'Please wait before sending another test email.' }, 429),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    await user.click(await screen.findByRole('button', { name: 'Send' }))

    expect(
      await screen.findByText('Please wait before sending another test email'),
    ).toBeInTheDocument()
  })

  it('shows an error when the test email fails', async () => {
    stubFetch({
      settings: makeServerSettings({ smtp_configured: true }),
      post: () => jsonBody({ detail: 'Could not send the test email' }, 502),
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    await user.click(await screen.findByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Could not send the test email')).toBeInTheDocument()
  })

  it('shows the mail server address, port and from address', async () => {
    stubFetch({
      settings: makeServerSettings({
        smtp_host: 'mail.example.com',
        smtp_port: 2525,
        smtp_from: 'noreply@example.com',
      }),
    })
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    expect(await screen.findByText('mail.example.com')).toBeInTheDocument()
    expect(screen.getByText('2525')).toBeInTheDocument()
    expect(screen.getByText('noreply@example.com')).toBeInTheDocument()
  })

  it('shows "Not set" for the address when SMTP is unconfigured', async () => {
    stubFetch({ settings: makeServerSettings({ smtp_configured: false, smtp_host: null }) })
    renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

    // Scoped to this row rather than findByText('Not set'), which now matches in the
    // single sign-on section too: the definition grid puts each value immediately after
    // its label, so the sibling is the value being asserted.
    const label = await screen.findByText('Server address')
    expect(label.nextElementSibling).toHaveTextContent('Not set')
  })

  describe('single sign-on panel', () => {
    /** The value cell for a definition-grid row, which sits immediately after its label. */
    function valueFor(label: string): Element | null {
      return screen.getByText(label).nextElementSibling
    }

    it('reports single sign-on as not configured, and says what to do', async () => {
      stubFetch({ settings: makeServerSettings() })
      renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

      expect(await screen.findByText('Not configured')).toBeInTheDocument()
      expect(screen.getByText(/No sign-in provider is configured/)).toBeInTheDocument()
      expect(valueFor('Issuer URL')).toHaveTextContent('Not set')
      expect(valueFor('Client ID')).toHaveTextContent('Not set')
    })

    it('shows the redirect URI even with no provider configured', async () => {
      // Derived from APP_BASE_URL rather than configured, and it is the value an operator
      // has to register with the provider BEFORE they can fill the rest in, so withholding
      // it until the group is complete would be backwards.
      stubFetch({ settings: makeServerSettings() })
      renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

      await screen.findByText('Not configured')
      expect(valueFor('Redirect URI')).toHaveTextContent(
        'http://localhost:5173/api/v1/auth/oidc/callback',
      )
    })

    it('reports a configured provider and its non-secret values', async () => {
      stubFetch({
        settings: makeServerSettings({
          oidc_configured: true,
          oidc_provider_name: 'Authentik',
          oidc_issuer: 'https://auth.example.com/application/o/isachore/',
          oidc_client_id: 'isachore-web',
        }),
      })
      renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

      expect(await screen.findByText('Configured')).toBeInTheDocument()
      expect(valueFor('Provider name')).toHaveTextContent('Authentik')
      expect(valueFor('Issuer URL')).toHaveTextContent(
        'https://auth.example.com/application/o/isachore/',
      )
      expect(valueFor('Client ID')).toHaveTextContent('isachore-web')
      expect(screen.queryByText(/No sign-in provider is configured/)).not.toBeInTheDocument()
    })

    it('never puts the client secret on the page', async () => {
      // It is not on the wire either (ServerSettingsRead has no such field), so this is a
      // belt-and-braces assertion against a future field being added and rendered.
      const settings = makeServerSettings({
        oidc_configured: true,
        oidc_client_id: 'isachore-web',
      })
      stubFetch({ settings: { ...settings, oidc_client_secret: 'shh' } as ServerSettingsData })
      const { container } = renderWithProviders(<ServerSettings />, {
        authValue: { user: admin },
      })

      await screen.findByText('Configured')
      expect(container.textContent).not.toContain('shh')
    })

    it('warns when password sign-in has been switched off', async () => {
      stubFetch({
        settings: makeServerSettings({ oidc_configured: true, oidc_only: true }),
      })
      renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

      expect(await screen.findByText(/Password sign-in is switched off/)).toBeInTheDocument()
    })

    it('does not warn about OIDC_ONLY when it is off', async () => {
      stubFetch({ settings: makeServerSettings({ oidc_configured: true }) })
      renderWithProviders(<ServerSettings />, { authValue: { user: admin } })

      await screen.findByText('Configured')
      expect(screen.queryByText(/Password sign-in is switched off/)).not.toBeInTheDocument()
    })
  })
})
