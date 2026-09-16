import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ApiTokenSettings from './ApiTokenSettings'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

const URL = '/api/v1/profile/api-token'
const CREATED_AT = '2026-09-16T08:30:00Z'
const TOKEN = 'isac_7fQ2mabcdefghijklmnopqrstuvwxyz0123456789xKp'

function render() {
  return renderWithProviders(<ApiTokenSettings />, { authValue: { user: makeUser() } })
}

describe('ApiTokenSettings', () => {
  it('offers to generate one when the account holds none', async () => {
    mockFetch([{ path: URL, body: { token: null } }])
    render()

    expect(await screen.findByText('None yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate token' })).toBeInTheDocument()
    expect(screen.getByLabelText('Current password')).toBeInTheDocument()
  })

  it('says what the token cannot reach', () => {
    // The boundary is the part somebody wiring up a client will otherwise discover as a
    // 403 they read as a bug. Same reasoning as TwoFactorSettings' SSO scope note.
    mockFetch([{ path: URL, body: { token: null } }])
    render()

    return waitFor(() =>
      expect(
        screen.getByText(/cannot reach your profile, your password, two-factor settings/i),
      ).toBeInTheDocument(),
    )
  })

  it('shows the creation date and a delete action when one exists', async () => {
    mockFetch([{ path: URL, body: { token: { created_at: CREATED_AT } } }])
    render()

    expect(await screen.findByText('Active')).toBeInTheDocument()
    expect(screen.getByText(/Created 16 Sept 2026/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete token' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Current password')).not.toBeInTheDocument()
  })

  it('generates a token, sends the password, and shows the value once', async () => {
    const fetchMock = mockFetch([
      { path: URL, body: { token: null } },
      { path: URL, method: 'POST', status: 201, body: { token: TOKEN, created_at: CREATED_AT } },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render()

    await user.type(await screen.findByLabelText('Current password'), 'password12345')
    await user.click(screen.getByRole('button', { name: 'Generate token' }))

    const dialog = within(await screen.findByRole('dialog'))
    expect(dialog.getByLabelText('Access token')).toHaveValue(TOKEN)
    expect(fetchMock).toHaveBeenCalledWith(
      URL,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ current_password: 'password12345' }),
      }),
    )

    await user.click(dialog.getByRole('button', { name: 'Done' }))

    // Dismissed and gone: the component holds the plaintext and nothing refetches it, so
    // this is what "shown once" means on the client. A later change that kept it in state,
    // or re-read it from the server, fails here.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByDisplayValue(TOKEN)).not.toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('copies the token to the clipboard', async () => {
    mockFetch([
      { path: URL, body: { token: null } },
      { path: URL, method: 'POST', status: 201, body: { token: TOKEN, created_at: CREATED_AT } },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render()

    await user.type(await screen.findByLabelText('Current password'), 'password12345')
    await user.click(screen.getByRole('button', { name: 'Generate token' }))
    const dialog = within(await screen.findByRole('dialog'))

    // Stubbed after userEvent.setup(), which installs a clipboard of its own, and clicked
    // with fireEvent so that stub is not reinstated. Same approach as the copy test in
    // HouseholdInvitations.test.tsx.
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    fireEvent.click(dialog.getByRole('button', { name: 'Copy token' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(TOKEN))
  })

  it('says so when the token could not be copied, rather than claiming it was', async () => {
    // jsdom leaves navigator.clipboard undefined, which is also what a browser does in any
    // non-secure context. The old `navigator.clipboard?.writeText(...)` resolved to
    // undefined there and fired the success toast having copied nothing - on a secret shown
    // exactly once. See lib/clipboard.ts.
    mockFetch([
      { path: URL, body: { token: null } },
      { path: URL, method: 'POST', status: 201, body: { token: TOKEN, created_at: CREATED_AT } },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render()

    await user.type(await screen.findByLabelText('Current password'), 'password12345')
    await user.click(screen.getByRole('button', { name: 'Generate token' }))
    const dialog = within(await screen.findByRole('dialog'))
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    fireEvent.click(dialog.getByRole('button', { name: 'Copy token' }))

    expect(await dialog.findByText(/Could not copy/i)).toBeInTheDocument()
    // The token is still on screen to copy by hand, which is what the message tells them.
    expect(dialog.getByLabelText('Access token')).toHaveValue(TOKEN)
  })

  it('reports a failed load instead of loading forever', async () => {
    mockFetch([{ path: URL, status: 500, body: { detail: 'Something broke' } }])
    render()

    expect(await screen.findByText('Something broke')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Generate token' })).not.toBeInTheDocument()
  })

  it('resolves to the real state when generating loses a race', async () => {
    // A token minted in another tab answers 409. Without the refetch the panel kept
    // offering Generate for an account that already had one, failing identically until
    // the page was reloaded.
    let created = false
    mockFetch([
      {
        path: URL,
        body: () => (created ? { token: { created_at: CREATED_AT } } : { token: null }),
      },
      {
        path: URL,
        method: 'POST',
        status: 409,
        body: () => {
          created = true
          return {
            detail: 'You already have an access token. Delete it before generating a new one.',
          }
        },
      },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render()

    await user.type(await screen.findByLabelText('Current password'), 'password12345')
    await user.click(screen.getByRole('button', { name: 'Generate token' }))

    expect(await screen.findByText('Active')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete token' })).toBeInTheDocument()
  })

  it('shows a wrong password inline and reveals nothing', async () => {
    mockFetch([
      { path: URL, body: { token: null } },
      {
        path: URL,
        method: 'POST',
        status: 400,
        body: { detail: 'Current password is incorrect' },
      },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render()

    await user.type(await screen.findByLabelText('Current password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Generate token' }))

    expect(await screen.findByText('Current password is incorrect')).toBeInTheDocument()
    // The second half: an error that still opened the dialog would pass on the first
    // assertion alone while showing an empty "here is your token".
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText('None yet')).toBeInTheDocument()
  })

  it('asks before deleting and returns to the empty state', async () => {
    const fetchMock = mockFetch([
      { path: URL, body: { token: { created_at: CREATED_AT } } },
      { path: URL, method: 'DELETE', status: 204 },
    ])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render()

    await user.click(await screen.findByRole('button', { name: 'Delete token' }))

    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.getByText('Delete access token?')).toBeInTheDocument()
    // Nothing has been sent yet: one GET, no DELETE. Without this the confirm step could
    // be decorative and the test would not notice.
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await user.click(dialog.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText('None yet')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(URL, expect.objectContaining({ method: 'DELETE' }))
  })

  it('keeps the token when the confirm dialog is cancelled', async () => {
    const fetchMock = mockFetch([{ path: URL, body: { token: { created_at: CREATED_AT } } }])
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render()

    await user.click(await screen.findByRole('button', { name: 'Delete token' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
