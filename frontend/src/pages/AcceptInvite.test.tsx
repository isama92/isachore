import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router'
import AcceptInvite from './AcceptInvite'
import { renderWithProviders } from '../test/utils'
import { makeInvitationInfo, makeUser } from '../test/fixtures'
import type { InvitationInfo } from '../lib/types'

const me = makeUser({ id: 2 })

// Stands in for /login: surfaces the `state.from` the invite page passed.
function FromProbe() {
  const location = useLocation()
  const state = location.state as { from?: string } | null
  return <div>from:{state?.from ?? 'none'}</div>
}

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
  info?: InvitationInfo
  infoStatus?: number
  accept?: (url: string) => Response
}): FetchMock {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'POST' && url.includes('/accept')) {
      return opts.accept ? opts.accept(url) : jsonBody(undefined, 204)
    }
    if (method === 'GET') {
      return opts.info ? jsonBody(opts.info) : jsonBody({ detail: 'nope' }, opts.infoStatus ?? 404)
    }
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('AcceptInvite', () => {
  it('shows who invited the recipient and offers Join when logged in', async () => {
    stubFetch({
      info: makeInvitationInfo({
        household_name: 'Flat 3B',
        invited_by: { id: 1, first_name: 'Alice', last_name: 'Adams' },
      }),
    })
    renderWithProviders(<AcceptInvite />, {
      route: '/invite?token=abc',
      authValue: { user: me },
    })

    expect(
      await screen.findByText("You've been invited to join Flat 3B by Alice Adams."),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Join household' })).toBeInTheDocument()
  })

  it('redirects a logged-out visitor to /login, carrying the token', async () => {
    stubFetch({ info: makeInvitationInfo() })
    renderWithProviders(
      <Routes>
        <Route path="/invite" element={<AcceptInvite />} />
        <Route path="/login" element={<FromProbe />} />
      </Routes>,
      { route: '/invite?token=abc', authValue: { user: null } },
    )

    // No card or button — straight to login, with the token preserved in
    // state.from so Login can return here afterwards.
    expect(await screen.findByText('from:/invite?token=abc')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Join household' })).not.toBeInTheDocument()
  })

  it('shows an invalid state for a bad/expired token', async () => {
    stubFetch({ infoStatus: 404 })
    renderWithProviders(<AcceptInvite />, { route: '/invite?token=bad', authValue: { user: me } })

    expect(await screen.findByText('Invitation expired or invalid')).toBeInTheDocument()
  })

  it('joins and navigates to the households list', async () => {
    let accepted = ''
    const fetchMock = stubFetch({
      info: makeInvitationInfo({ household_name: 'Flat 3B' }),
      accept: (url) => {
        accepted = url
        return jsonBody(undefined, 204)
      },
    })
    const { value } = renderWithProviders(
      <Routes>
        <Route path="/invite" element={<AcceptInvite />} />
        <Route path="/households" element={<div>households-list</div>} />
      </Routes>,
      { route: '/invite?token=abc', authValue: { user: me } },
    )
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Join household' }))

    expect(await screen.findByText('households-list')).toBeInTheDocument()
    expect(accepted).toContain('/api/v1/invitations/abc/accept')
    expect(fetchMock).toHaveBeenCalled()
    // Joining grants a role, which the sidebar and RequireRole read from the auth context.
    // A helper's nav happens to match the no-household nav, so nothing looks wrong today -
    // which is exactly why this needs pinning rather than eyeballing.
    expect(value.refresh).toHaveBeenCalled()
  })

  it('surfaces an already-a-member conflict', async () => {
    stubFetch({
      info: makeInvitationInfo(),
      accept: () => jsonBody({ detail: 'You are already a member of this household' }, 409),
    })
    renderWithProviders(<AcceptInvite />, { route: '/invite?token=abc', authValue: { user: me } })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Join household' }))
    expect(
      await screen.findByText("You're already a member of this household."),
    ).toBeInTheDocument()
  })

  it('surfaces a generic join error', async () => {
    stubFetch({
      info: makeInvitationInfo(),
      accept: () => jsonBody({ detail: 'Something broke' }, 500),
    })
    renderWithProviders(<AcceptInvite />, { route: '/invite?token=abc', authValue: { user: me } })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Join household' }))
    expect(await screen.findByText('Something broke')).toBeInTheDocument()
  })
})
