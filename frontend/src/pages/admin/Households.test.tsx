import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminHouseholds from './Households'
import { renderWithProviders } from '../../test/utils'
import { makeHousehold, makeUser } from '../../test/fixtures'
import type { Household } from '../../lib/types'

const admin = makeUser({ id: 1, first_name: 'Admin', last_name: 'User', is_admin: true })

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
    if (method === 'GET' && path.endsWith('/api/v1/admin/households')) {
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

function lastAdminGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(
    ([url, init]) =>
      (init?.method ?? 'GET').toUpperCase() === 'GET' &&
      String(url).split('?')[0].endsWith('/api/v1/admin/households'),
  )
  return String(calls.at(-1)?.[0] ?? '')
}

const active = makeHousehold({ id: 1, name: 'Active One', member_count: 1 })
const gone = makeHousehold({ id: 2, name: 'Gone One', deleted_at: '2026-06-01T00:00:00Z' })

const rowOf = (name: string) => screen.getByText(name).closest('tr')!

describe('AdminHouseholds', () => {
  it('shows every household with a status badge and the right per-row action', async () => {
    stubFetch({ households: [active, gone] })
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })

    await screen.findByText('Active One')
    expect(within(rowOf('Active One')).getByText('Active')).toBeInTheDocument()
    expect(within(rowOf('Gone One')).getByText('Deleted')).toBeInTheDocument()
    expect(within(rowOf('Active One')).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(within(rowOf('Gone One')).getByRole('button', { name: 'Restore' })).toBeInTheDocument()
  })

  it('defaults to the active filter and sends the chosen status', async () => {
    const fetchMock = stubFetch({ households: [active] })
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Active One')
    expect(lastAdminGet(fetchMock)).toContain('status=active')

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Deleted' }))
    await waitFor(() => expect(lastAdminGet(fetchMock)).toContain('status=deleted'))
  })

  it('links to create and edit under the admin path', async () => {
    stubFetch({ households: [makeHousehold({ id: 7, name: 'Active One', timezone: 'UTC' })] })
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })

    await screen.findByText('Active One')
    expect(screen.getByRole('link', { name: 'Add household' })).toHaveAttribute(
      'href',
      '/admin/households/new',
    )
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute(
      'href',
      '/admin/households/7/edit',
    )
  })

  it('soft-deletes an active household after confirmation', async () => {
    let deleted = ''
    stubFetch({
      households: [active],
      mutate: (method, url) => {
        if (method === 'DELETE') deleted = url
        return jsonBody(undefined, 204)
      },
    })
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Active One')
    await user.click(within(rowOf('Active One')).getByRole('button', { name: 'Delete' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Delete household' }))

    await waitFor(() => expect(deleted).toContain('/api/v1/admin/households/1'))
  })

  it('debounces the name filter into the request query', async () => {
    const fetchMock = stubFetch({ households: [active] })
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })
    const user = userEvent.setup()

    await screen.findByText('Active One')
    await user.type(screen.getByPlaceholderText('Filter by name'), 'beach')
    await waitFor(() => expect(lastAdminGet(fetchMock)).toContain('name=beach'))
  })

  it('surfaces a load error with the generic message', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonBody({ detail: 'boom' }, 500),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })

    expect(await screen.findByText('Failed to load households')).toBeInTheDocument()
  })

  it('shows the empty state when there are no households', async () => {
    stubFetch({ households: [] })
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })

    expect(await screen.findByText('No results.')).toBeInTheDocument()
  })

  it('restores a deleted household', async () => {
    let restored = ''
    stubFetch({
      households: [gone],
      mutate: (method, url) => {
        if (method === 'POST') restored = url
        return jsonBody(makeHousehold({ id: 2, name: 'Gone One' }))
      },
    })
    renderWithProviders(<AdminHouseholds />, { authValue: { user: admin } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Gone One')
    await user.click(within(rowOf('Gone One')).getByRole('button', { name: 'Restore' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Restore household' }))

    await waitFor(() => expect(restored).toContain('/api/v1/admin/households/2/restore'))
  })
})
