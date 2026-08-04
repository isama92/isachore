import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ColumnDef } from '@tanstack/react-table'
import { useAuth } from '../auth/useAuth'
import { api } from '../lib/api'
import { ownedHouseholdIds } from '../lib/permissions'
import { endpoints } from '../lib/endpoints'
import { formatDateTime } from '../lib/chores'
import { isLogAction, logActionLabel, logFieldLabel } from '../lib/logs'
import { fullName } from '../lib/user'
import { LOG_ACTIONS, type HistoryFilterOptions, type LogEntry } from '../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type LogFilters = { household_id: string; user_id: string; action: string }

// Radix Selects can't hold an empty value, so the "all" option uses a sentinel
// that maps back to an omitted filter.
const ALL = 'all'

const EMPTY_OPTIONS: HistoryFilterOptions = { households: [], members: [] }

export default function Logs() {
  const { t } = useTranslation()
  const { memberships } = useAuth()

  const table = useServerTable<LogEntry, LogFilters>({
    endpoint: endpoints.logs,
    storageKey: 'logs',
    initial: {
      sortBy: 'created_at',
      sortDir: 'desc',
      pageSize: 10,
      filters: { household_id: '', user_id: '', action: '' },
    },
  })

  // Memoised so it is a stable dependency of the options effect. /completions/filters is
  // deliberately NOT narrowed server-side (it feeds Home and Unscheduled, which every role
  // uses), so the narrowing happens here - the third page to do so, after History and
  // Statistics. Ownership, not a role: an organiser who does not own the household has no rows
  // here at all.
  //
  // The person picker keeps the dead end those two pages have: it lists members of households
  // the caller does not own, and the payload carries no member -> household association to
  // narrow it by. Picking one yields an empty page rather than anything leaking (those names
  // are already on Home). It also cannot offer somebody who has since left, which matters more
  // here than there, since this is a 90-day retrospective and people do leave. The fix, if it
  // ever bites, is a logs/filters endpoint selecting the distinct actors the log itself holds.
  const owned = useMemo(() => ownedHouseholdIds(memberships), [memberships])
  const [options, setOptions] = useState<HistoryFilterOptions>(EMPTY_OPTIONS)

  // Latest-value refs so the options effect can prune a remembered filter without taking
  // them as dependencies (which would refetch the options).
  const setFiltersRef = useRef(table.setFilters)
  const filtersRef = useRef(table.filters)
  useEffect(() => {
    setFiltersRef.current = table.setFilters
    filtersRef.current = table.filters
  })

  useEffect(() => {
    let cancelled = false
    api
      .get<HistoryFilterOptions>(endpoints.completions.filters)
      .then((data) => {
        if (cancelled) return
        const scoped = { ...data, households: data.households.filter((h) => owned.has(h.id)) }
        setOptions(scoped)
        // A remembered id outlives whatever made it valid - and a household transferred away
        // is the one that matters here, because below two owned households the Select is
        // hidden and nothing on screen could clear it (the hook only forgets storage on a
        // 400/422, and this filter merely empties the page). Everything goes in ONE setFilters
        // call: two setFilter calls in a tick would lose the first, see the hook.
        const { household_id, user_id, action } = filtersRef.current
        const dead: Partial<LogFilters> = {}
        if (household_id !== '' && !scoped.households.some((h) => String(h.id) === household_id)) {
          dead.household_id = ''
        }
        if (user_id !== '' && !data.members.some((m) => String(m.id) === user_id)) {
          dead.user_id = ''
        }
        // Needs no network - the action list is ours - but it rides in the same call. Only
        // reachable when a release drops an action, since stored settings are validated for
        // type rather than for domain.
        if (action !== '' && !isLogAction(action)) dead.action = ''
        if (Object.keys(dead).length > 0) setFiltersRef.current(dead)
      })
      .catch(() => {
        if (!cancelled) setOptions(EMPTY_OPTIONS)
      })
    return () => {
      cancelled = true
    }
  }, [owned])

  const columns: ColumnDef<LogEntry>[] = [
    {
      // The only sortable column, and its id IS the server's sort key. The rest are joins or
      // off the endpoint's whitelist, so a sortable header there would push a key the server
      // rejects - which the hook recovers from by clearing the stored settings, but only after
      // the user has seen it fail.
      id: 'created_at',
      accessorFn: (e) => e.created_at,
      header: t('logs.headers.when'),
      cell: ({ row }) => formatDateTime(row.original.created_at),
      meta: { cellClassName: 'font-medium text-muted-foreground' },
    },
    {
      id: 'household',
      accessorFn: (e) => e.household.name,
      header: t('logs.headers.household'),
      enableSorting: false,
      cell: ({ row }) => (
        <span className="font-medium text-muted-foreground">{row.original.household.name}</span>
      ),
    },
    {
      id: 'actor',
      header: t('logs.headers.actor'),
      enableSorting: false,
      // `by_admin` rides along as a muted suffix rather than a column of its own: it is rare,
      // and it belongs beside the person it qualifies. Never the operator's name - a site
      // admin may be a stranger to this household, so the API sends only the flag.
      cell: ({ row }) => (
        <span className="flex items-center gap-1.5">
          {row.original.actor ? (
            fullName(row.original.actor)
          ) : (
            <span className="text-muted-foreground">{t('logs.unknownActor')}</span>
          )}
          {row.original.by_admin && (
            <span className="text-[13px] text-muted-foreground">{t('logs.byAdmin')}</span>
          )}
        </span>
      ),
    },
    {
      id: 'action',
      header: t('logs.headers.action'),
      enableSorting: false,
      // The undone closure's owner rides along as a muted suffix, the same shape `by_admin`
      // uses on the actor cell, and for a stronger reason: without it "Sam / Completion undone
      // / Bins" does not say whose work went, which is the whole point of recording an undo
      // separately from the completion it erased - and the reason `completion_undone` and
      // `skip_undone` are two actions rather than one flagged one. A suffix rather than a
      // column of its own because only those two actions carry a target, so a column would be
      // empty on three rows in five. The wording matches History's confirmation copy ("This
      // entry was recorded by ..."), which is where the owner will have met the idea already.
      cell: ({ row }) => (
        <span className="flex flex-wrap items-center gap-x-1.5">
          <span className="font-medium">{logActionLabel(t, row.original.action)}</span>
          {row.original.target && (
            <span className="text-[13px] text-muted-foreground">
              {t('logs.recordedBy', { name: fullName(row.original.target) })}
            </span>
          )}
        </span>
      ),
    },
    {
      id: 'chore_title',
      header: t('logs.headers.chore'),
      enableSorting: false,
      // The snapshot the entry was written with, so a rename or a delete does not rewrite it.
      // Note a rename records the title the chore ENDS with, so its row names something that
      // did not exist a moment earlier while older rows keep the old name - unavoidable with a
      // name snapshot, and the `title` entry in the Changed column is what explains it.
      //
      // Nullable on the wire (an undone closure copies the occurrence's title, which is
      // nullable), and no current write path leaves it empty - but a bare null would render as
      // a blank cell rather than as an absence, so it gets its own placeholder.
      cell: ({ row }) => (
        <span className={row.original.chore_title ? 'font-semibold' : 'text-muted-foreground'}>
          {row.original.chore_title ?? t('logs.noChore')}
        </span>
      ),
    },
    {
      id: 'changed_fields',
      header: t('logs.headers.changes'),
      enableSorting: false,
      // Only an update carries any, so the placeholder is the common case rather than an edge
      // one. Rendered in the order the API sent (it decides that; sorting here would invent
      // an order), and comma-joined rather than badged: ten fields is reachable, and ten
      // badges per row would out-shout the action they belong to.
      cell: ({ row }) => {
        const fields = row.original.changed_fields
        return (
          <span className="text-muted-foreground">
            {fields.length === 0
              ? t('logs.noChanges')
              : fields.map((field) => logFieldLabel(t, field)).join(', ')}
          </span>
        )
      },
    },
  ]

  return (
    <main className="w-full px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">{t('logs.title')}</h1>

      {/* The plain banner, with no role="alert" or scrollIntoView: this page is read-only, so
          the only thing that can fail is the load, and it renders at the top of a page whose
          table is empty at the same moment. */}
      {table.error && (
        <p className="mb-4 text-[13px] font-bold text-danger">{t('logs.loadError')}</p>
      )}

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        {/* Always rendered, for the same reason History's outcome filter is: the payload says
            nothing about which actions exist, so there is nothing to hide it on. */}
        <Select
          value={table.filters.action || ALL}
          onValueChange={(v) => table.setFilter('action', v === ALL ? '' : v)}
        >
          <SelectTrigger className="sm:w-56" aria-label={t('logs.filters.actionLabel')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('logs.filters.actionAll')}</SelectItem>
            {LOG_ACTIONS.map((action) => (
              <SelectItem key={action} value={action}>
                {logActionLabel(t, action)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {options.members.length > 1 && (
          <Select
            value={table.filters.user_id || ALL}
            onValueChange={(v) => table.setFilter('user_id', v === ALL ? '' : v)}
          >
            <SelectTrigger className="sm:w-56" aria-label={t('logs.filters.userLabel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('logs.filters.userAll')}</SelectItem>
              {options.members.map((m) => (
                <SelectItem key={m.id} value={String(m.id)}>
                  {fullName(m)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {options.households.length > 1 && (
          <Select
            value={table.filters.household_id || ALL}
            onValueChange={(v) => table.setFilter('household_id', v === ALL ? '' : v)}
          >
            <SelectTrigger className="sm:w-56" aria-label={t('logs.filters.householdLabel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('logs.filters.householdAll')}</SelectItem>
              {options.households.map((h) => (
                <SelectItem key={h.id} value={String(h.id)}>
                  {h.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <DataTable
        columns={columns}
        table={table}
        minWidthClassName="min-w-[900px]"
        emptyMessage={t('logs.empty')}
      />
    </main>
  )
}
