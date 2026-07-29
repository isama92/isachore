import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { endpoints } from '@/lib/endpoints'
import type { HistoryFilterOptions } from '@/lib/types'

const EMPTY: HistoryFilterOptions = { households: [], members: [] }

// The household + member option lists for the chore filter bars, fetched once on mount.
// Shared with History and Statistics, which is why the endpoint lives under completions:
// all four views offer the same choices, so there is no separate options endpoint per page.
//
// A failure falls back to empty rather than surfacing an error, which hides the filter bar:
// the page's own list request carries the error the user needs to see, and a broken filter
// bar on top of it would just be noise. setState happens only inside .then/.catch (never in
// the effect body) for eslint-plugin-react-hooks' set-state-in-effect rule.
export function useFilterOptions(): HistoryFilterOptions {
  const [options, setOptions] = useState<HistoryFilterOptions>(EMPTY)
  useEffect(() => {
    let cancelled = false
    api
      .get<HistoryFilterOptions>(endpoints.completions.filters)
      .then((opts) => {
        if (!cancelled) setOptions(opts)
      })
      .catch(() => {
        if (!cancelled) setOptions(EMPTY)
      })
    return () => {
      cancelled = true
    }
  }, [])
  return options
}
