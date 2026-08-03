import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { toast } from 'sonner'
import Households from './Households'
import { renderWithProviders, membershipsFor } from '../test/utils'
import { makeHousehold, makeUser } from '../test/fixtures'
import type { Household } from '../lib/types'

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

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
  households: Household[]
  total?: number
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/households')) {
      return jsonBody({
        items: opts.households,
        total: opts.total ?? opts.households.length,
        page: 1,
        page_size: 20,
      })
    }
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastHouseholdsGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(
    ([url, init]) =>
      (init?.method ?? 'GET').toUpperCase() === 'GET' &&
      String(url).split('?')[0].endsWith('/api/v1/households'),
  )
  return String(calls.at(-1)?.[0] ?? '')
}

describe('Households', () => {
  it('renders a row per household with member and chore counts', async () => {
    stubFetch({
      households: [makeHousehold({ id: 1, name: 'Flat 3B', member_count: 2, chore_count: 5 })],
    })
    renderWithProviders(<Households />, { authValue: { user: me } })

    const row = (await screen.findByText('Flat 3B')).closest('tr')!
    expect(within(row).getByText('2')).toBeInTheDocument()
    expect(within(row).getByText('5')).toBeInTheDocument()
  })

  it('links to the create and edit pages when the user owns the household', async () => {
    // makeHousehold defaults admin_id to 1, the signed-in user's id.
    stubFetch({ households: [makeHousehold({ id: 7, name: 'Flat 3B' })] })
    renderWithProviders(<Households />, { authValue: { user: me } })

    await screen.findByText('Flat 3B')
    expect(screen.getByRole('link', { name: 'Add household' })).toHaveAttribute(
      'href',
      '/households/new',
    )
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/households/7/edit')
  })

  it('shows View (not Edit/Delete) for a household the user only helps in', async () => {
    stubFetch({ households: [makeHousehold({ id: 8, name: 'Not Mine', admin_id: 99 })] })
    renderWithProviders(<Households />, {
      authValue: { user: me, memberships: membershipsFor('helper', 8) },
    })

    await screen.findByText('Not Mine')
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute('href', '/households/8/edit')
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('shows Edit to an organiser who does not own the household, but no Delete', async () => {
    // An organiser cannot rename or delete it, but they DO set deputy and helper roles and
    // manage its invitations on that page, so an eye labelled "View" hid a real capability.
    // Delete stays owner-only, which is what keeps the two rows distinguishable.
    stubFetch({ households: [makeHousehold({ id: 8, name: 'Not Mine', admin_id: 99 })] })
    renderWithProviders(<Households />, {
      authValue: { user: me, memberships: membershipsFor('organiser', 8) },
    })

    await screen.findByText('Not Mine')
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/households/8/edit')
    expect(screen.queryByRole('link', { name: 'View' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('shows View to a deputy, so the pencil really tracks the role', async () => {
    // The other side of the clause: same non-owner household, one role lower.
    stubFetch({ households: [makeHousehold({ id: 8, name: 'Not Mine', admin_id: 99 })] })
    renderWithProviders(<Households />, {
      authValue: { user: me, memberships: membershipsFor('deputy', 8) },
    })

    await screen.findByText('Not Mine')
    expect(screen.getByRole('link', { name: 'View' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('debounces the name filter into the request query', async () => {
    const fetchMock = stubFetch({ households: [makeHousehold({ name: 'Flat 3B' })] })
    renderWithProviders(<Households />, { authValue: { user: me } })
    const user = userEvent.setup()

    await screen.findByText('Flat 3B')
    await user.type(screen.getByPlaceholderText('Filter by name'), 'beach')
    await waitFor(() => expect(lastHouseholdsGet(fetchMock)).toContain('name=beach'))
  })

  it('soft-deletes a household after confirmation', async () => {
    let deleted = ''
    const fetchMock = stubFetch({
      households: [makeHousehold({ id: 3, name: 'Flat 3B' })],
      mutate: (method, url) => {
        if (method === 'DELETE') deleted = url
        return jsonBody(undefined, 204)
      },
    })
    const toastSpy = vi.spyOn(toast, 'success')
    const { value } = renderWithProviders(<Households />, { authValue: { user: me } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    const row = (await screen.findByText('Flat 3B')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Delete' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Delete household' }))

    await waitFor(() => expect(deleted).toContain('/api/v1/households/3'))
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true)
    expect(toastSpy).toHaveBeenCalled()
    // A soft-deleted household drops out of the caller's memberships, so deleting one
    // shrinks their roles and the sidebar has to be told. Deleting your last household
    // would otherwise leave it offering management pages that no longer resolve.
    expect(value.refresh).toHaveBeenCalled()
  })

  it('surfaces a load error', async () => {
    const fetchMock = vi.fn(async () => jsonBody({ detail: 'nope' }, 500))
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(<Households />, { authValue: { user: me } })

    // A failed list load shows the generic message (the page's own `error` is
    // for mutations), matching the admin Users page pattern.
    expect(await screen.findByText('Failed to load households')).toBeInTheDocument()
  })

  it('shows a first-run empty state when the user has no households', async () => {
    stubFetch({ households: [] })
    renderWithProviders(
      <Routes>
        <Route path="/" element={<Households />} />
      </Routes>,
      { authValue: { user: me }, route: '/' },
    )

    // Nothing provisions a household on sign-up, so this is what a brand-new
    // account sees; the generic "No results." would read like a loading bug.
    expect(await screen.findByText('No households yet')).toBeInTheDocument()
    expect(
      screen.getByText('Create one to start adding chores, or wait for an invitation.'),
    ).toBeInTheDocument()
  })

  it('falls back to the generic empty message when a name filter matches nothing', async () => {
    const user = userEvent.setup()
    stubFetch({ households: [] })
    renderWithProviders(
      <Routes>
        <Route path="/" element={<Households />} />
      </Routes>,
      { authValue: { user: me }, route: '/' },
    )
    await screen.findByText('No households yet')

    await user.type(screen.getByPlaceholderText('Filter by name'), 'zzz')

    // With a filter active, an empty table means no matches, so inviting the user
    // to create their first household would be wrong.
    expect(await screen.findByText('No results.')).toBeInTheDocument()
    expect(screen.queryByText('No households yet')).not.toBeInTheDocument()
  })

  it('falls back to the generic empty message on an out-of-range page', async () => {
    // useServerTable does not clamp `page`, so deleting the last row of page 2
    // leaves an empty item list with a non-zero total. The user owns 10
    // households; telling them they have none would be flatly wrong.
    stubFetch({ households: [], total: 10 })
    renderWithProviders(
      <Routes>
        <Route path="/" element={<Households />} />
      </Routes>,
      { authValue: { user: me }, route: '/' },
    )

    expect(await screen.findByText('No results.')).toBeInTheDocument()
    expect(screen.queryByText('No households yet')).not.toBeInTheDocument()
  })
})
