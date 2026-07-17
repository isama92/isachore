import { act, renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter, useSearchParams } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { jsonResponse } from '../../test/utils'
import { useServerTable } from './useServerTable'

type Row = { id: number; name: string }

function makePage(items: Row[], total: number, page = 1, page_size = 20) {
  return { items, total, page, page_size }
}

function stubFetch(handler?: (url: string) => unknown) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    return jsonResponse(200, handler ? handler(url) : makePage([{ id: 1, name: 'A' }], 1))
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter initialEntries={['/x']}>{children}</MemoryRouter>
}

const initial = {
  sortBy: 'created_at',
  sortDir: 'desc' as const,
  pageSize: 20,
  filters: { status: 'active', role: '', q: '' },
}

function renderTable() {
  return renderHook(
    () => {
      const table = useServerTable<Row>({ endpoint: '/api/x', initial })
      const [params] = useSearchParams()
      return { table, params }
    },
    { wrapper },
  )
}

describe('useServerTable', () => {
  it('fetches the first page with the initial params and omits empty filters', async () => {
    const fetchMock = stubFetch(() => makePage([{ id: 1, name: 'A' }], 45))
    const { result } = renderTable()

    await waitFor(() => expect(result.current.table.loading).toBe(false))

    const url = String(fetchMock.mock.calls[0]![0])
    expect(url).toContain('/api/x?')
    expect(url).toContain('page=1')
    expect(url).toContain('page_size=20')
    expect(url).toContain('sort_by=created_at')
    expect(url).toContain('sort_dir=desc')
    expect(url).toContain('status=active')
    // role and q default to '' -> unset -> not sent
    expect(url).not.toContain('role=')
    expect(url).not.toContain('q=')

    expect(result.current.table.rows).toHaveLength(1)
    expect(result.current.table.total).toBe(45)
    expect(result.current.table.pageCount).toBe(3) // ceil(45 / 20)
  })

  it('changing a filter refetches with the value, resets to page 1, and syncs the URL', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    act(() => result.current.table.setPage(2))
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)![0])).toContain('page=2'))

    act(() => result.current.table.setFilter('status', 'disabled'))
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.at(-1)![0])
      expect(last).toContain('status=disabled')
      expect(last).toContain('page=1')
    })
    expect(result.current.params.get('status')).toBe('disabled')
    // page reset to default -> omitted from the URL
    expect(result.current.params.get('page')).toBeNull()
  })

  it('an "all" filter (empty value) is persisted in the URL but not sent to the API', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    act(() => result.current.table.setFilter('status', ''))
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)![0])).not.toContain('status='))
    // '' differs from the default 'active', so it is kept in the URL to survive refresh
    expect(result.current.params.get('status')).toBe('')
  })

  it('sorting refetches with sort_by/sort_dir and syncs the URL', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    act(() => result.current.table.setSort('email', 'asc'))
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.at(-1)![0])
      expect(last).toContain('sort_by=email')
      expect(last).toContain('sort_dir=asc')
    })
    expect(result.current.params.get('sort_by')).toBe('email')
    expect(result.current.params.get('sort_dir')).toBe('asc')
  })

  it('surfaces an API error message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(500, { detail: 'boom' })),
    )
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))
    expect(result.current.table.error).toBe('boom')
    expect(result.current.table.rows).toHaveLength(0)
  })

  it('changing the page size resets to page 1', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    act(() => result.current.table.setPage(3))
    await waitFor(() => expect(result.current.params.get('page')).toBe('3'))

    act(() => result.current.table.setPageSize(50))
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.at(-1)![0])
      expect(last).toContain('page_size=50')
      expect(last).toContain('page=1')
    })
    expect(result.current.params.get('page')).toBeNull()
  })

  it('honours initial.sortDir as the default direction (not a hardcoded desc)', async () => {
    const fetchMock = stubFetch()
    const ascInitial = { ...initial, sortDir: 'asc' as const }
    const { result } = renderHook(
      () => {
        const table = useServerTable<Row>({ endpoint: '/api/x', initial: ascInitial })
        const [params] = useSearchParams()
        return { table, params }
      },
      { wrapper },
    )
    await waitFor(() => expect(result.current.table.loading).toBe(false))
    expect(String(fetchMock.mock.calls[0]![0])).toContain('sort_dir=asc')
    expect(result.current.table.sortDir).toBe('asc')

    // Toggling to desc persists it; toggling back to the asc default clears it
    // from the URL and still derives asc (would regress if the default were
    // hardcoded to desc).
    act(() => result.current.table.setSort('created_at', 'desc'))
    await waitFor(() => expect(result.current.params.get('sort_dir')).toBe('desc'))
    act(() => result.current.table.setSort('created_at', 'asc'))
    await waitFor(() => expect(result.current.params.get('sort_dir')).toBeNull())
    expect(result.current.table.sortDir).toBe('asc')
  })

  it('preserves unrelated query params when updating table state', async () => {
    stubFetch()
    const { result } = renderHook(
      () => {
        const table = useServerTable<Row>({ endpoint: '/api/x', initial })
        const [params] = useSearchParams()
        return { table, params }
      },
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <MemoryRouter initialEntries={['/x?tab=details']}>{children}</MemoryRouter>
        ),
      },
    )
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    act(() => result.current.table.setFilter('status', 'disabled'))
    await waitFor(() => expect(result.current.params.get('status')).toBe('disabled'))
    expect(result.current.params.get('tab')).toBe('details')
  })

  it('reload() refetches the current page', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    const before = fetchMock.mock.calls.length
    act(() => result.current.table.reload())
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(before + 1))
  })
})
