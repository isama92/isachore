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
      return jsonBody({ items: tags, total: tags.length, page: 1, page_size: 20 })
    }
    if (method !== 'GET' && opts.mutate) return opts.mutate(method, url)
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastTagsGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(
    ([url, init]) =>
      (init?.method ?? 'GET').toUpperCase() === 'GET' &&
      String(url).split('?')[0].endsWith('/api/v1/tags'),
  )
  return String(calls.at(-1)?.[0] ?? '')
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

  it('lets a multi-household user pick the household and pushes it into the query', async () => {
    const fetchMock = stubFetch({
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
    await waitFor(() => expect(lastTagsGet(fetchMock)).toContain('household_id=2'))
    expect(await screen.findByText('beach-only')).toBeInTheDocument()
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
    // The list reloads after a delete: a second tags GET fires.
    await waitFor(() => {
      const tagGets = fetchMock.mock.calls.filter(
        ([url, init]) =>
          (init?.method ?? 'GET').toUpperCase() === 'GET' &&
          String(url).split('?')[0].endsWith('/api/v1/tags'),
      ).length
      expect(tagGets).toBeGreaterThanOrEqual(2)
    })
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

  it('shows guidance when the user has no household', async () => {
    stubFetch({ tags: [], households: [] })
    renderWithProviders(<Tags />, { authValue: { user: me } })
    expect(
      await screen.findByText('You need a household before you can add tags.'),
    ).toBeInTheDocument()
  })

  it('shows an error when loading tags fails', async () => {
    // A household exists (so the DataTable renders), but the tags fetch fails.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input).split('?')[0]
        if (path.endsWith('/api/v1/households')) {
          return jsonBody({
            items: [makeHousehold({ id: 1 })],
            total: 1,
            page: 1,
            page_size: 100,
          })
        }
        return jsonBody({ detail: 'boom' }, 500)
      }),
    )
    renderWithProviders(<Tags />, { authValue: { user: me } })
    expect(await screen.findByText('Failed to load tags')).toBeInTheDocument()
  })
})
