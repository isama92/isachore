import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HouseholdInvitations } from './HouseholdInvitations'
import { renderWithProviders } from '../../test/utils'
import { makeHouseholdInvitation } from '../../test/fixtures'
import type { HouseholdInvitation } from '../../lib/types'

const BASE = '/api/v1/households/5'

type FetchMock = ReturnType<typeof vi.fn>

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

function stubFetch(opts: {
  invitations: HouseholdInvitation[]
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/invitations')) return jsonBody(opts.invitations)
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('HouseholdInvitations', () => {
  it('shows Copy + Revoke for pending and only Delete for expired', async () => {
    stubFetch({
      invitations: [
        makeHouseholdInvitation({ id: 1, status: 'pending' }),
        makeHouseholdInvitation({ id: 2, status: 'expired' }),
      ],
    })
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)

    const pendingRow = (await screen.findByText('Pending')).closest('li')!
    const expiredRow = screen.getByText('Expired').closest('li')!
    expect(within(pendingRow).getByRole('button', { name: 'Copy link' })).toBeInTheDocument()
    expect(within(pendingRow).getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
    expect(within(expiredRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(within(expiredRow).queryByRole('button', { name: 'Copy link' })).not.toBeInTheDocument()
  })

  it('adds a member (creates an invitation) and shows it in the list', async () => {
    const fetchMock = stubFetch({
      invitations: [],
      mutate: (method) =>
        method === 'POST'
          ? jsonBody(makeHouseholdInvitation({ id: 9, status: 'pending' }), 201)
          : jsonBody(undefined, 204),
    })
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)
    const user = userEvent.setup()

    await screen.findByText('No invitations yet.')
    await user.click(screen.getByRole('button', { name: 'Add member' }))

    expect(await screen.findByText('Pending')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([url, init]) => {
      return init?.method === 'POST' && String(url).endsWith(`${BASE}/invitations`)
    })
    expect(post).toBeTruthy()
  })

  it('copies a pending invite link to the clipboard', async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    stubFetch({
      invitations: [
        makeHouseholdInvitation({ id: 1, url: 'http://host/invite?token=abc', status: 'pending' }),
      ],
    })
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Copy link' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('http://host/invite?token=abc'))
  })

  it('shows Delete (not Revoke) for accepted and revoked invites', async () => {
    stubFetch({
      invitations: [
        makeHouseholdInvitation({ id: 1, status: 'accepted' }),
        makeHouseholdInvitation({ id: 2, status: 'revoked' }),
      ],
    })
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)

    const acceptedRow = (await screen.findByText('Accepted')).closest('li')!
    const revokedRow = screen.getByText('Revoked').closest('li')!
    expect(within(acceptedRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(within(acceptedRow).queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
    expect(within(revokedRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('revokes a pending invitation, which becomes Revoked (kept, deletable)', async () => {
    let revoked = ''
    stubFetch({
      invitations: [makeHouseholdInvitation({ id: 3, status: 'pending' })],
      mutate: (method, url) => {
        if (method === 'POST' && url.includes('/revoke')) {
          revoked = url
          return jsonBody(makeHouseholdInvitation({ id: 3, status: 'revoked' }))
        }
        return jsonBody(undefined, 204)
      },
    })
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Revoke' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Revoke invitation' }))

    await waitFor(() => expect(revoked).toContain(`${BASE}/invitations/3/revoke`))
    // The row stays, now Revoked, with a Delete button.
    expect(await screen.findByText('Revoked')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('disables Add member at 5 live-pending and re-enables after a revoke', async () => {
    const five = Array.from({ length: 5 }, (_, i) =>
      makeHouseholdInvitation({ id: i + 1, status: 'pending' }),
    )
    stubFetch({
      invitations: five,
      mutate: (method, url) =>
        method === 'POST' && url.includes('/revoke')
          ? jsonBody(makeHouseholdInvitation({ id: 1, status: 'revoked' }))
          : jsonBody(undefined, 204),
    })
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findAllByText('Pending')
    expect(screen.getByRole('button', { name: 'Add member' })).toBeDisabled()

    // Revoke one -> live-pending drops to 4 -> Add member re-enables.
    await user.click(screen.getAllByRole('button', { name: 'Revoke' })[0])
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Revoke invitation' }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Add member' })).not.toBeDisabled(),
    )
  })

  it('deletes an expired invitation', async () => {
    let deleted = ''
    stubFetch({
      invitations: [makeHouseholdInvitation({ id: 4, status: 'expired' })],
      mutate: (method, url) => {
        if (method === 'DELETE') deleted = url
        return jsonBody(undefined, 204)
      },
    })
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deleted).toContain(`${BASE}/invitations/4`))
    expect(await screen.findByText('No invitations yet.')).toBeInTheDocument()
  })

  it('surfaces a load error', async () => {
    const fetchMock = vi.fn(async () => jsonBody({ detail: 'nope' }, 500))
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(<HouseholdInvitations basePath={BASE} />)

    expect(await screen.findByText('nope')).toBeInTheDocument()
  })
})
