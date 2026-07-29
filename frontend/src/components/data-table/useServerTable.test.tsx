import { act, renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter, useSearchParams } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { jsonResponse } from '../../test/utils'
import { clearTableSettings, useServerTable } from './useServerTable'

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

  it('setFilters applies several filters in one update', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    act(() => result.current.table.setPage(2))
    await waitFor(() => expect(result.current.params.get('page')).toBe('2'))

    // Both survive. Two setFilter calls here would not: setSearchParams is a
    // navigation, so the second would start from the same location as the first
    // and overwrite it.
    act(() => result.current.table.setFilters({ status: 'disabled', role: 'admin' }))
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.at(-1)![0])
      expect(last).toContain('status=disabled')
      expect(last).toContain('role=admin')
      expect(last).toContain('page=1')
    })
    expect(result.current.params.get('status')).toBe('disabled')
    expect(result.current.params.get('role')).toBe('admin')
  })

  // The `loading` assertions are the point of these two. Without the guards the URL
  // does not change either, so no refetch happens with or without them and a call
  // count alone would pass regardless. What breaks is that `mutate` sets loading true
  // and nothing clears it: no URL change, no request, no `.finally`.
  it('setFilters is a no-op when every value already matches', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    const before = fetchMock.mock.calls.length
    act(() => result.current.table.setFilters({ status: 'active', role: '' }))
    expect(fetchMock.mock.calls.length).toBe(before)
    expect(result.current.table.loading).toBe(false)
  })

  it('setFilters ignores an explicit undefined rather than sending it', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    act(() => result.current.table.setFilters({ status: 'disabled', role: undefined }))
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)![0])).toContain('disabled'))
    // Would arrive as the literal string "undefined" if the entries were cast rather
    // than filtered.
    expect(String(fetchMock.mock.calls.at(-1)![0])).not.toContain('undefined')
    expect(result.current.params.get('role')).toBeNull()
  })

  it('setFilter is a no-op when the value already matches', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    const before = fetchMock.mock.calls.length
    act(() => result.current.table.setFilter('status', 'active'))
    expect(fetchMock.mock.calls.length).toBe(before)
    expect(result.current.table.loading).toBe(false)
  })

  it('reload() refetches the current page', async () => {
    const fetchMock = stubFetch()
    const { result } = renderTable()
    await waitFor(() => expect(result.current.table.loading).toBe(false))

    const before = fetchMock.mock.calls.length
    act(() => result.current.table.reload())
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(before + 1))
  })

  describe('with a storageKey', () => {
    const KEY = 'isachore-table-things'

    function renderStored(entries = ['/x']) {
      return renderHook(
        () => {
          const table = useServerTable<Row>({ endpoint: '/api/x', storageKey: 'things', initial })
          const [params] = useSearchParams()
          return { table, params }
        },
        {
          wrapper: ({ children }: { children: ReactNode }) => (
            <MemoryRouter initialEntries={entries}>{children}</MemoryRouter>
          ),
        },
      )
    }

    function save(settings: unknown) {
      localStorage.setItem(KEY, JSON.stringify(settings))
    }

    function stored(): Record<string, unknown> {
      return JSON.parse(localStorage.getItem(KEY)!) as Record<string, unknown>
    }

    it('restores page size, sort and filters when the URL carries none', async () => {
      save({
        pageSize: 50,
        sortBy: 'name',
        sortDir: 'asc',
        filters: { status: 'disabled', role: 'admin', q: '' },
      })
      const fetchMock = stubFetch()
      const { result } = renderStored()
      await waitFor(() => expect(result.current.table.loading).toBe(false))

      const url = String(fetchMock.mock.calls[0]![0])
      expect(url).toContain('page_size=50')
      expect(url).toContain('sort_by=name')
      expect(url).toContain('sort_dir=asc')
      expect(url).toContain('status=disabled')
      expect(url).toContain('role=admin')
      // Restored values act as this mount's defaults, so the URL stays clean
      // rather than being rewritten with them.
      expect(result.current.params.get('sort_by')).toBeNull()
      expect(result.current.params.get('page_size')).toBeNull()
    })

    it('always starts on page 1, however the settings were saved', async () => {
      // `page: 7` is smuggled in by hand: nothing writes it, and nothing may read it.
      save({ pageSize: 50, sortBy: 'name', sortDir: 'asc', filters: {}, page: 7 })
      const fetchMock = stubFetch()
      const { result } = renderStored()
      await waitFor(() => expect(result.current.table.loading).toBe(false))

      const url = String(fetchMock.mock.calls[0]![0])
      expect(url).toContain('page=1')
      expect(url).not.toContain('page=7')
      expect(result.current.table.page).toBe(1)
    })

    it('lets an explicit URL param win over the stored value', async () => {
      save({
        pageSize: 50,
        sortBy: 'name',
        sortDir: 'asc',
        filters: { status: 'disabled', role: '', q: '' },
      })
      const fetchMock = stubFetch()
      const { result } = renderStored(['/x?sort_by=email&status=active'])
      await waitFor(() => expect(result.current.table.loading).toBe(false))

      const url = String(fetchMock.mock.calls[0]![0])
      expect(url).toContain('sort_by=email')
      expect(url).toContain('status=active')
      // Untouched by the URL, so the stored value still applies.
      expect(url).toContain('page_size=50')
    })

    it('remembers a sort, page size and filter change, but never the page', async () => {
      stubFetch()
      const { result } = renderStored()
      await waitFor(() => expect(result.current.table.loading).toBe(false))

      act(() => result.current.table.setSort('name', 'asc'))
      await waitFor(() => expect(stored().sortBy).toBe('name'))
      expect(stored().sortDir).toBe('asc')

      act(() => result.current.table.setPageSize(50))
      await waitFor(() => expect(stored().pageSize).toBe(50))

      act(() => result.current.table.setFilter('status', 'disabled'))
      await waitFor(() =>
        expect((stored().filters as Record<string, string>).status).toBe('disabled'),
      )

      act(() => result.current.table.setPage(3))
      await waitFor(() => expect(result.current.table.page).toBe(3))
      expect(stored()).not.toHaveProperty('page')
    })

    // Each shape is its own case so a failure names the one that broke. 1000 is over
    // the API's page_size cap, 20.5 is not an integer, 42 is not a string.
    it.each([
      'not json at all',
      'null',
      '[1,2,3]',
      '"a string"',
      JSON.stringify({ pageSize: 1000, sortBy: '', sortDir: 'sideways', filters: 'nope' }),
      JSON.stringify({ pageSize: 20.5, sortBy: 42, sortDir: null, filters: { status: 7 } }),
    ])('falls back to the page defaults for unusable stored settings: %s', async (raw) => {
      localStorage.setItem(KEY, raw)
      const fetchMock = stubFetch()
      const { result } = renderStored()
      await waitFor(() => expect(result.current.table.loading).toBe(false))

      const url = String(fetchMock.mock.calls[0]![0])
      expect(url).toContain('page_size=20')
      expect(url).toContain('sort_by=created_at')
      expect(url).toContain('sort_dir=desc')
      expect(url).toContain('status=active')
    })

    it('drops a stored filter key this table does not have, keeping the rest', async () => {
      save({ pageSize: 20, sortBy: 'name', sortDir: 'asc', filters: { gone: 'x', role: 'admin' } })
      const fetchMock = stubFetch()
      const { result } = renderStored()
      await waitFor(() => expect(result.current.table.loading).toBe(false))

      const url = String(fetchMock.mock.calls[0]![0])
      expect(url).not.toContain('gone=')
      // Still-valid neighbours survive: the fallback is per field, not all-or-nothing.
      expect(url).toContain('sort_by=name')
      expect(url).toContain('role=admin')
      // A filter absent from storage falls back to the page's own default.
      expect(url).toContain('status=active')
    })

    it('forgets settings the server rejects, but keeps them through a server error', async () => {
      const saved = {
        pageSize: 20,
        sortBy: 'a_column_that_went_away',
        sortDir: 'desc',
        filters: { status: 'active', role: '', q: '' },
      }

      save(saved)
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse(422, { detail: 'bad sort_by' })),
      )
      const rejected = renderStored()
      await waitFor(() => expect(rejected.result.current.table.loading).toBe(false))
      // Otherwise this table would 422 on every future visit, with no way out.
      expect(localStorage.getItem(KEY)).toBeNull()
      rejected.unmount()

      save(saved)
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse(500, { detail: 'boom' })),
      )
      const errored = renderStored()
      await waitFor(() => expect(errored.result.current.table.loading).toBe(false))
      // A blip is not the stored state's fault; throwing away the user's sort
      // over one would be its own bug.
      expect(stored()).toEqual(saved)
    })

    it('recovers in place from a rejected stored sort, without needing a reload', async () => {
      save({
        pageSize: 20,
        sortBy: 'a_column_that_went_away',
        sortDir: 'desc',
        filters: { status: 'active', role: '', q: '' },
      })
      // Only the dead sort is rejected, so a healed request succeeds.
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('a_column_that_went_away')) {
          return jsonResponse(422, { detail: 'bad sort_by' })
        }
        return jsonResponse(200, makePage([{ id: 1, name: 'A' }], 1))
      })
      vi.stubGlobal('fetch', fetchMock)
      const { result } = renderStored()

      // Heals on its own, within the same mount: clearing storage alone would not be
      // enough, because the restored value is ALSO this mount's default, so every
      // later derive would land back on the dead sort and only a browser reload would
      // recover. Resetting the default is what makes the retry use a live sort.
      await waitFor(() => expect(result.current.table.rows).toHaveLength(1))
      expect(result.current.table.error).toBeNull()
      expect(String(fetchMock.mock.calls[0]![0])).toContain('a_column_that_went_away')
      const healed = String(fetchMock.mock.calls.at(-1)![0])
      expect(healed).not.toContain('a_column_that_went_away')
      expect(healed).toContain('sort_by=created_at')
      expect(localStorage.getItem(KEY)).not.toContain('a_column_that_went_away')

      // And it stays healed once the user interacts.
      act(() => result.current.table.setFilter('status', 'disabled'))
      await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)![0])).toContain('disabled'))
      expect(String(fetchMock.mock.calls.at(-1)![0])).not.toContain('a_column_that_went_away')
    })

    it('still renders when storage refuses the write', async () => {
      const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation((): never => {
        throw new Error('quota exceeded')
      })
      try {
        stubFetch()
        const { result } = renderStored()
        // Would throw out of the effect and take the page down if the write were
        // unguarded, which matters because it runs on mount for every table.
        await waitFor(() => expect(result.current.table.loading).toBe(false))
        expect(result.current.table.rows).toHaveLength(1)
      } finally {
        setItem.mockRestore()
      }
    })

    it('clearTableSettings forgets every table, leaving other keys alone', async () => {
      save({ pageSize: 50, sortBy: 'name', sortDir: 'asc', filters: {} })
      localStorage.setItem('isachore-table-somewhere-else', '{}')
      localStorage.setItem('isachore-theme', 'mocha')

      clearTableSettings()

      expect(localStorage.getItem(KEY)).toBeNull()
      expect(localStorage.getItem('isachore-table-somewhere-else')).toBeNull()
      // Theme and language are this browser's preferences, not one account's data.
      expect(localStorage.getItem('isachore-theme')).toBe('mocha')
    })

    it('writes nothing when a table opts out of persistence', async () => {
      stubFetch()
      const { result } = renderTable()
      await waitFor(() => expect(result.current.table.loading).toBe(false))

      act(() => result.current.table.setSort('name', 'asc'))
      await waitFor(() => expect(result.current.table.sortBy).toBe('name'))
      expect(localStorage.length).toBe(0)
    })
  })
})
