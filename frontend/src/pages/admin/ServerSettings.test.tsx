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
        '/api/v1/settings',
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
        '/api/v1/settings/test-email',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(toastSpy).toHaveBeenCalledWith('Test email sent to admin@example.com')
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

    expect(await screen.findByText('Not set')).toBeInTheDocument()
  })
})
