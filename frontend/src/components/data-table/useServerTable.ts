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

/**
 * Everything about a table except which page you are on: what `initial` supplies,
 * and exactly what gets remembered across visits. The two being the same type is
 * the point rather than a coincidence, see `defaults` in the hook below.
 *
 * The page is deliberately excluded: it can be out of range once rows are deleted
 * (nothing clamps it, see the note on the hook), so every arrival starts at 1.
 */
export type TableSettings<Filters extends FilterSet> = Omit<ServerTableState<Filters>, 'page'>

export type UseServerTableOptions<Filters extends FilterSet> = {
  endpoint: string
  // When set, this table's settings are remembered in localStorage under
  // `isachore-table-<storageKey>`, so leaving the page and coming back keeps
  // them. Omit it to keep the state URL-only.
  storageKey?: string
  initial: TableSettings<Filters>
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
  setFilters: (patch: Partial<Filters>) => void
  reload: () => void
}

function positiveInt(raw: string | null, fallback: number): number {
  const n = Number(raw)
  return Number.isInteger(n) && n >= 1 ? n : fallback
}

function parseSortDir(raw: string | null, fallback: SortDir): SortDir {
  return raw === 'asc' || raw === 'desc' ? raw : fallback
}

// One key per table, matching the `isachore-<thing>` convention of the theme and
// language keys (src/theme/ThemeProvider.tsx, src/i18n/i18n.ts).
const STORAGE_PREFIX = 'isachore-table-'

// The API caps page_size at 100, so a bigger stored value would 422 every request.
const MAX_PAGE_SIZE = 100

/**
 * Read a table's remembered settings. localStorage is untrusted input that
 * outlives any release, so each field is validated and falls back to `initial`
 * *on its own*: one stale value must not discard the others.
 */
function readSettings<Filters extends FilterSet>(
  key: string,
  initial: TableSettings<Filters>,
): TableSettings<Filters> {
  let parsed: unknown
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key)
    if (raw === null) return initial
    parsed = JSON.parse(raw)
  } catch {
    // Unreadable storage or malformed JSON: behave as if nothing was saved.
    return initial
  }
  if (typeof parsed !== 'object' || parsed === null) return initial
  const stored = parsed as Record<string, unknown>
  const storedFilters =
    typeof stored.filters === 'object' && stored.filters !== null
      ? (stored.filters as Record<string, unknown>)
      : {}
  // Rebuilt from the page's own filter keys, so a key an older release stored is
  // dropped and one this release added falls back, rather than landing undefined.
  const filters = {} as Filters
  for (const filterKey of Object.keys(initial.filters) as (keyof Filters & string)[]) {
    const value = storedFilters[filterKey]
    ;(filters as FilterSet)[filterKey] =
      typeof value === 'string' ? value : initial.filters[filterKey]
  }
  const pageSize = stored.pageSize
  return {
    pageSize:
      typeof pageSize === 'number' &&
      Number.isInteger(pageSize) &&
      pageSize >= 1 &&
      pageSize <= MAX_PAGE_SIZE
        ? pageSize
        : initial.pageSize,
    sortBy:
      typeof stored.sortBy === 'string' && stored.sortBy !== '' ? stored.sortBy : initial.sortBy,
    sortDir:
      stored.sortDir === 'asc' || stored.sortDir === 'desc' ? stored.sortDir : initial.sortDir,
    filters,
  }
}

// Guarded, unlike the theme and language writes, because those happen on an
// explicit click while this one runs on mount for every table: storage being
// unavailable or full (private mode, quota) must not take the page down over a
// convenience feature.
function writeSettings(key: string, json: string): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, json)
  } catch {
    // Nothing to do: the table still works, it just will not be remembered.
  }
}

function clearSettings(key: string): void {
  try {
    localStorage.removeItem(STORAGE_PREFIX + key)
  } catch {
    // As above.
  }
}

// Which account the remembered settings belong to. Deliberately outside
// STORAGE_PREFIX so the sweep below can never mistake it for some table's settings,
// and removed alongside them.
const OWNER_KEY = 'isachore-tables-owner'

/**
 * Forget every table's remembered settings. Called when a session ends (logout, a
 * 401 expiry): the saved filters name colleagues and households (`user_id`,
 * `household_id`) and the admin tables save name/email search terms, so on a shared
 * device the next person to sign in would otherwise inherit them. Keyed off the
 * prefix rather than a list, so a table added later is covered without anyone
 * remembering to register it.
 */
export function clearTableSettings(): void {
  try {
    const keys = Object.keys(localStorage).filter((key) => key.startsWith(STORAGE_PREFIX))
    for (const key of keys) localStorage.removeItem(key)
    localStorage.removeItem(OWNER_KEY)
  } catch {
    // Storage unavailable: nothing was saved to forget.
  }
}

/**
 * Hand the remembered settings to `userId`, forgetting them first if they belonged
 * to anyone else.
 *
 * The owner is persisted rather than compared in memory so the check survives a page
 * load, which is the whole point: someone who closes the tab without logging out
 * leaves no id behind, and once their cookie lapses the next account to sign in would
 * inherit their filters. Ids get pruned by the pages that offer them, but the admin
 * tables' name/email search terms do not, so that is the value this protects.
 *
 * Settings with no recorded owner cannot be attributed, so they are forgotten too.
 * That costs everyone their table preferences once, on the first sign-in after this
 * ships, and is a no-op on a browser that has none.
 *
 * Storing the last account's id is itself a small identifier, and a far smaller one
 * than the search terms it stops leaking.
 */
export function claimTableSettings(userId: number): void {
  try {
    const owner = localStorage.getItem(OWNER_KEY)
    if (owner !== String(userId)) {
      const unattributed =
        owner === null && Object.keys(localStorage).some((key) => key.startsWith(STORAGE_PREFIX))
      if (owner !== null || unattributed) clearTableSettings()
    }
    localStorage.setItem(OWNER_KEY, String(userId))
  } catch {
    // Storage unavailable: nothing is remembered, so nothing can leak.
  }
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
 * With a `storageKey`, page size / sort / filters are also remembered in
 * localStorage, so they survive leaving the page and coming back, not just a
 * refresh (which the URL alone already covered). An explicit URL still wins, so a
 * shared or bookmarked link shows what it says. The page number is not
 * remembered, see `TableSettings`. Note that opening someone else's link therefore
 * also *replaces* what you had remembered for that table, since what gets saved is
 * whatever state committed; `clearTableSettings()` wipes the lot on logout.
 *
 * Note: the current page is not clamped to pageCount. Every filter/sort/size
 * change resets to page 1, so this only affects a stale deep-link to a
 * now-out-of-range page, which renders an empty page recoverable via Previous.
 */
export function useServerTable<Row, Filters extends FilterSet = FilterSet>({
  endpoint,
  storageKey,
  initial,
}: UseServerTableOptions<Filters>): UseServerTableResult<Row, Filters> {
  const [searchParams, setSearchParams] = useSearchParams()
  const filterKeys = Object.keys(initial.filters) as (keyof Filters & string)[]

  // Read storage once, at mount, and let what comes back *be* this mount's
  // defaults. Everything below already treats "the default" two ways -- fall back
  // to it when the URL omits a key, and omit it from the URL when it is the current
  // value -- so restoring through that one notion gives "URL wins over storage,
  // storage wins over the page's own defaults" for free, with no extra branch and no
  // mount-time URL rewrite (which would cost a second fetch and a flicker).
  //
  // Read once, not per render, and the two consumers must stay in step:
  // `deriveState` and `applyOwnedParams` have to agree on what "the default" is, or
  // a value equal to it gets dropped from the URL by one and resolved differently by
  // the other. A per-render read would mostly coincide with this, since the effect
  // below keeps storage equal to the committed state, but it would make the pair's
  // agreement an accident of timing rather than something the code guarantees.
  //
  // State rather than a ref because the fetch below resets it when the server
  // rejects what was restored: that changes the derived state, so it has to
  // re-render. `pageDefaults` is the pristine `initial`, snapshotted so the reset has
  // a stable value to return to and so the fetch effect can depend on it without
  // refiring (`initial` itself is a fresh object literal on every render). Note this
  // snapshots regardless of `storageKey`, so a caller computing `initial.filters`
  // from props would see them frozen at mount; every caller passes a constant today.
  const [pageDefaults] = useState(initial)
  const [defaults, setDefaults] = useState(() =>
    storageKey ? readSettings(storageKey, pageDefaults) : pageDefaults,
  )

  // Derive the effective state from the URL, applying defaults for absent keys.
  // A key that is present (even with an empty value) wins over the default, so
  // "All" (value '') is distinguishable from "never touched" (falls back to the
  // default, e.g. 'active').
  const deriveState = (params: URLSearchParams): ServerTableState<Filters> => {
    const filters = {} as Filters
    for (const key of filterKeys) {
      ;(filters as FilterSet)[key] = params.has(key) ? params.get(key)! : defaults.filters[key]
    }
    return {
      page: positiveInt(params.get('page'), 1),
      pageSize: positiveInt(params.get('page_size'), defaults.pageSize),
      sortBy: params.get('sort_by') ?? defaults.sortBy,
      sortDir: parseSortDir(params.get('sort_dir'), defaults.sortDir),
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
    if (state.pageSize !== defaults.pageSize) params.set('page_size', String(state.pageSize))
    if (state.sortBy !== defaults.sortBy) params.set('sort_by', state.sortBy)
    if (state.sortDir !== defaults.sortDir) params.set('sort_dir', state.sortDir)
    for (const key of filterKeys) {
      if (state.filters[key] !== defaults.filters[key]) params.set(key, state.filters[key])
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
  // Serialised once, so the same string is both the payload and a stable effect
  // dependency (the settings object itself is rebuilt every render).
  const settingsJson = JSON.stringify({
    pageSize: state.pageSize,
    sortBy: state.sortBy,
    sortDir: state.sortDir,
    filters: state.filters,
  } satisfies TableSettings<Filters>)

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
        // A remembered sort or filter the server no longer accepts (a release
        // renaming a sort key, say) would wedge this table for good, so forget it.
        // Both halves are needed: dropping the stored copy stops it coming back on
        // the next visit, and resetting `defaults` heals THIS session, because the
        // restored value is also the fallback every later derive would land on --
        // otherwise each interaction resends the rejected sort and only a browser
        // reload recovers. Resetting also stops the write effect persisting the
        // rejected value again. Only the param-validation statuses: a 401/403/404/5xx
        // is not the stored state's fault, and throwing away a valid saved sort over
        // a network blip would be its own bug.
        //
        // It does not check WHERE the rejected parameter came from, so opening a stale
        // shared link also forgets that table's saved settings, even though storage
        // was innocent. Accepted rather than fixed: telling the two apart would mean
        // tracking each parameter's origin, and the cost is one preference set on a
        // link that was already broken. The URL itself is left as it is, since nothing
        // here navigates and the user can leave it.
        if (storageKey && err instanceof ApiError && (err.status === 400 || err.status === 422)) {
          clearSettings(storageKey)
          setDefaults(pageDefaults)
        }
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })
    return () => {
      ignore = true
    }
    // storageKey and pageDefaults are here for the .catch above. Both are fixed for
    // the life of the table, so neither ever causes a refetch.
  }, [endpoint, apiQuery, reloadToken, storageKey, pageDefaults])

  // Remembered from an effect, not from `mutate`: the setSearchParams updater is a
  // function React may call more than once, which is no place for a side effect,
  // and this way what gets saved is always the state that actually committed.
  // A localStorage write is not setState, so this does not trip set-state-in-effect.
  useEffect(() => {
    if (storageKey) writeSettings(storageKey, settingsJson)
  }, [storageKey, settingsJson])

  // Setters flip `loading` here (an event handler, not the effect) and write the
  // next state to the URL; the derived state + effect then refetch. The updater form
  // is used so the merge is expressed against `prev` rather than a captured copy,
  // but note it buys no extra freshness: react-router hands the updater the current
  // render's params, so two calls in the same tick both start from the SAME params
  // and the last silently overwrites the first. Its own docs say so ("Multiple calls
  // to setSearchParams in the same tick will not build on the prior value"). Anything
  // that has to change two things at once must do it in one mutate -- see setFilters.
  //
  // Each setter's early-return guard is load-bearing for more than saving a fetch:
  // `mutate` flips `loading` true, and with no URL change there is no request and so
  // no `.finally` to flip it back, which would leave the table spinning forever.
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
  // Several filters in one update, for callers that must change more than one at a
  // time. Calling setFilter twice in a tick would lose the first write, see mutate.
  const setFilters = (patch: Partial<Filters>) => {
    // Partial<Filters> also admits an explicit undefined, which would otherwise pass
    // the guard, survive the spread and reach the query as the string "undefined".
    const entries = Object.entries(patch).filter(([, value]) => value !== undefined) as [
      keyof Filters & string,
      string,
    ][]
    if (!entries.some(([key, value]) => state.filters[key] !== value)) return
    const defined = Object.fromEntries(entries) as Partial<Filters>
    mutate((s) => ({ ...s, filters: { ...s.filters, ...defined }, page: 1 }))
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
    setFilters,
    reload,
  }
}
