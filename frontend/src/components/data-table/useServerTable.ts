import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api, ApiError } from '@/lib/api'
import type { Page } from '@/lib/types'

export type SortDir = 'asc' | 'desc'

// A filter set is a flat map of string values. An empty string means "no
// filter" for that key: it is omitted from the API request entirely, so the
// server treats it as unset (e.g. an "All" option uses value '').
export type FilterSet = Record<string, string>

export type ServerTableState<Filters extends FilterSet> = {
  page: number
  pageSize: number
  sortBy: string
  sortDir: SortDir
  filters: Filters
}

export type UseServerTableOptions<Filters extends FilterSet> = {
  endpoint: string
  initial: {
    sortBy: string
    sortDir: SortDir
    pageSize: number
    filters: Filters
  }
}

export type UseServerTableResult<Row, Filters extends FilterSet> = {
  rows: Row[]
  total: number
  loading: boolean
  error: string | null
  page: number
  pageSize: number
  sortBy: string
  sortDir: SortDir
  filters: Filters
  pageCount: number
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  setSort: (sortBy: string, sortDir: SortDir) => void
  setFilter: (key: keyof Filters & string, value: string) => void
  reload: () => void
}

function positiveInt(raw: string | null, fallback: number): number {
  const n = Number(raw)
  return Number.isInteger(n) && n >= 1 ? n : fallback
}

function parseSortDir(raw: string | null, fallback: SortDir): SortDir {
  return raw === 'asc' || raw === 'desc' ? raw : fallback
}

/**
 * Server-driven table state, synced to the URL query string. The hook owns
 * page / page size / sort / filters, keeps them in the URL (bookmarkable and
 * refresh-safe), and fetches only the current page from `endpoint`, which must
 * return a `Page<Row>` envelope.
 *
 * Filter values that equal an empty string are treated as "unset" and dropped
 * from the request; values that equal the initial default are omitted from the
 * URL to keep it clean, but a non-default value (including '' when the default
 * is non-empty, e.g. the "All" status) is persisted so it survives a refresh.
 *
 * Note: the current page is not clamped to pageCount. Every filter/sort/size
 * change resets to page 1, so this only affects a stale deep-link to a
 * now-out-of-range page, which renders an empty page recoverable via Previous.
 */
export function useServerTable<Row, Filters extends FilterSet = FilterSet>({
  endpoint,
  initial,
}: UseServerTableOptions<Filters>): UseServerTableResult<Row, Filters> {
  const [searchParams, setSearchParams] = useSearchParams()
  const filterKeys = Object.keys(initial.filters) as (keyof Filters & string)[]

  // Derive the effective state from the URL, applying defaults for absent keys.
  // A key that is present (even with an empty value) wins over the default, so
  // "All" (value '') is distinguishable from "never touched" (falls back to the
  // default, e.g. 'active').
  const deriveState = (params: URLSearchParams): ServerTableState<Filters> => {
    const filters = {} as Filters
    for (const key of filterKeys) {
      ;(filters as FilterSet)[key] = params.has(key) ? params.get(key)! : initial.filters[key]
    }
    return {
      page: positiveInt(params.get('page'), 1),
      pageSize: positiveInt(params.get('page_size'), initial.pageSize),
      sortBy: params.get('sort_by') ?? initial.sortBy,
      sortDir: parseSortDir(params.get('sort_dir'), initial.sortDir),
      filters,
    }
  }

  // Merge the table's owned keys into a base params object, preserving any
  // unrelated query params already on the route. A key at its default value is
  // dropped so the URL stays clean; a non-default value (including '' when the
  // default is non-empty, e.g. the "All" status) is written so it survives a
  // refresh.
  const applyOwnedParams = (
    base: URLSearchParams,
    state: ServerTableState<Filters>,
  ): URLSearchParams => {
    const params = new URLSearchParams(base)
    for (const key of ['page', 'page_size', 'sort_by', 'sort_dir', ...filterKeys]) {
      params.delete(key)
    }
    if (state.page !== 1) params.set('page', String(state.page))
    if (state.pageSize !== initial.pageSize) params.set('page_size', String(state.pageSize))
    if (state.sortBy !== initial.sortBy) params.set('sort_by', state.sortBy)
    if (state.sortDir !== initial.sortDir) params.set('sort_dir', state.sortDir)
    for (const key of filterKeys) {
      if (state.filters[key] !== initial.filters[key]) params.set(key, state.filters[key])
    }
    return params
  }

  // Build the request query: always page/size/sort, plus non-empty filters.
  const toApiQuery = (state: ServerTableState<Filters>): string => {
    const params = new URLSearchParams()
    params.set('page', String(state.page))
    params.set('page_size', String(state.pageSize))
    params.set('sort_by', state.sortBy)
    params.set('sort_dir', state.sortDir)
    for (const key of filterKeys) {
      const value = state.filters[key]
      if (value !== '') params.set(key, value)
    }
    return params.toString()
  }

  const state = deriveState(searchParams)
  const apiQuery = toApiQuery(state)

  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  // Starts true so the very first render shows a loading state before the effect
  // resolves; subsequent fetches flip it true from the setters below (never
  // synchronously in the effect body -- that trips set-state-in-effect).
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let ignore = false
    api
      .get<Page<Row>>(`${endpoint}?${apiQuery}`)
      .then((data) => {
        if (ignore) return
        setRows(data.items)
        setTotal(data.total)
        setError(null)
      })
      .catch((err: unknown) => {
        if (ignore) return
        setError(err instanceof ApiError ? err.message : 'Failed to load')
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })
    return () => {
      ignore = true
    }
  }, [endpoint, apiQuery, reloadToken])

  // Setters flip `loading` here (an event handler, not the effect) and write the
  // next state to the URL; the derived state + effect then refetch. The next
  // state is computed from `prev` *inside* the updater (react-router chains
  // functional updaters), so two setters firing in the same tick each merge onto
  // the freshest params rather than a stale render snapshot.
  const mutate = (next: (s: ServerTableState<Filters>) => ServerTableState<Filters>) => {
    setLoading(true)
    setError(null)
    setSearchParams((prev) => applyOwnedParams(prev, next(deriveState(prev))), { replace: true })
  }

  const setPage = (page: number) => {
    if (page === state.page) return
    mutate((s) => ({ ...s, page }))
  }
  const setPageSize = (pageSize: number) => {
    if (pageSize === state.pageSize) return
    mutate((s) => ({ ...s, pageSize, page: 1 }))
  }
  const setSort = (sortBy: string, sortDir: SortDir) => {
    if (sortBy === state.sortBy && sortDir === state.sortDir) return
    mutate((s) => ({ ...s, sortBy, sortDir, page: 1 }))
  }
  const setFilter = (key: keyof Filters & string, value: string) => {
    if (state.filters[key] === value) return
    mutate((s) => ({ ...s, filters: { ...s.filters, [key]: value }, page: 1 }))
  }
  const reload = () => {
    setLoading(true)
    setError(null)
    setReloadToken((n) => n + 1)
  }

  const pageCount = Math.max(1, Math.ceil(total / state.pageSize))

  return {
    rows,
    total,
    loading,
    error,
    page: state.page,
    pageSize: state.pageSize,
    sortBy: state.sortBy,
    sortDir: state.sortDir,
    filters: state.filters,
    pageCount,
    setPage,
    setPageSize,
    setSort,
    setFilter,
    reload,
  }
}
