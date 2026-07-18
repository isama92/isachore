import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import Tags from './Tags'
import { renderWithProviders } from '../test/utils'
import { makeHousehold, makeTag, makeUser } from '../test/fixtures'
import type { Household, Tag } from '../lib/types'

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
  tags: Tag[] | ((householdId: string) => Tag[])
  households?: Household[]
  mutate?: (method: string, url: string) => Response
}): FetchMock {
  const households = opts.households ?? [makeHousehold({ id: 1, name: 'Test Household' })]
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.split('?')[0]
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && path.endsWith('/api/v1/households')) {
      return jsonBody({ items: households, total: households.length, page: 1, page_size: 100 })
    }
    if (method === 'GET' && path.endsWith('/api/v1/tags')) {
      const householdId = new URL(url, 'http://x').searchParams.get('household_id') ?? ''
      const tags = typeof opts.tags === 'function' ? opts.tags(householdId) : opts.tags
      return jsonBody(tags)
    }
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('Tags', () => {
  it('lists a household tags by name', async () => {
    stubFetch({ tags: [makeTag({ id: 3, name: 'deep-clean', color: '#0d9488' })] })
    renderWithProviders(<Tags />, { authValue: { user: me } })
    expect(await screen.findByText('deep-clean')).toBeInTheDocument()
  })

  it('shows an empty state when there are no tags', async () => {
    stubFetch({ tags: [] })
    renderWithProviders(<Tags />, { authValue: { user: me } })
    expect(await screen.findByText('No tags yet.')).toBeInTheDocument()
  })

  it('links each row to its edit page', async () => {
    stubFetch({ tags: [makeTag({ id: 7, name: 'shared' })] })
    renderWithProviders(<Tags />, { authValue: { user: me } })
    await screen.findByText('shared')
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/tags/7/edit')
  })

  it('hides the household selector for a single household', async () => {
    stubFetch({ tags: [makeTag({ id: 3, name: 'deep-clean' })] })
    renderWithProviders(<Tags />, { authValue: { user: me } })
    await screen.findByText('deep-clean')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
  })

  it('lets a multi-household user pick the household and refetches its tags', async () => {
    stubFetch({
      households: [
        makeHousehold({ id: 1, name: 'Flat 3B' }),
        makeHousehold({ id: 2, name: 'Beach House' }),
      ],
      tags: (hid) =>
        hid === '2'
          ? [makeTag({ id: 9, name: 'beach-only' })]
          : [makeTag({ id: 3, name: 'deep-clean' })],
    })
    renderWithProviders(<Tags />, { authValue: { user: me } })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    expect(await screen.findByText('deep-clean')).toBeInTheDocument()
    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))
    expect(await screen.findByText('beach-only')).toBeInTheDocument()
    expect(screen.queryByText('deep-clean')).not.toBeInTheDocument()
  })

  it('deletes a tag after confirming in the dialog and reloads', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    let deleted = ''
    const fetchMock = stubFetch({
      tags: [makeTag({ id: 7, name: 'shared' })],
      mutate: (method, url) => {
        if (method === 'DELETE') deleted = url
        return jsonBody(undefined, 204)
      },
    })
    renderWithProviders(<Tags />, { authValue: { user: me } })

    const row = (await screen.findByText('shared')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Delete' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete tag' }),
    )
    await waitFor(() => expect(deleted).toContain('/api/v1/tags/7'))
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true)
    expect(toastSpy).toHaveBeenCalledWith('Tag deleted')
  })

  it('does not delete when the dialog is cancelled', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = stubFetch({ tags: [makeTag({ id: 7, name: 'shared' })] })
    renderWithProviders(<Tags />, { authValue: { user: me } })

    const row = (await screen.findByText('shared')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Delete' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }),
    )
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('shows an error when loading fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network')
      }),
    )
    renderWithProviders(<Tags />, { authValue: { user: me } })
    expect(await screen.findByText('Failed to load tags')).toBeInTheDocument()
  })
})
