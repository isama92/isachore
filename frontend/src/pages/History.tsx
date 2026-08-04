import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { Undo2Icon } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { householdIdsWithRole } from '../lib/permissions'
import { endpoints } from '../lib/endpoints'
import { formatDateTime } from '../lib/chores'
import { fullName } from '../lib/user'
import type { HistoryEntry, HistoryFilterOptions } from '../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

type HistoryFilters = { user_id: string; household_id: string; outcome: string }

// Radix Selects can't hold an empty value, so the "all" option uses a sentinel
// that maps back to an omitted filter.
const ALL = 'all'

const EMPTY_OPTIONS: HistoryFilterOptions = { households: [], members: [] }

export default function History() {
  const { t } = useTranslation()
  const { user, memberships } = useAuth()

  const table = useServerTable<HistoryEntry, HistoryFilters>({
    endpoint: endpoints.completions.root,
    storageKey: 'history',
    initial: {
      sortBy: 'created_at',
      sortDir: 'desc',
      pageSize: 10,
      // `outcome` gets its URL param, its remembered value and its request serialisation
      // free, since the hook derives its filter keys from this object. Empty = both kinds.
      filters: { user_id: '', household_id: '', outcome: '' },
    },
  })

  // The households this page has data for. /completions/filters is deliberately NOT
  // role-narrowed (it also feeds the Home and Unscheduled filter bars, which every role
  // uses), so the narrowing happens here instead - otherwise the picker would offer a
  // household the caller is only a helper in and selecting it would come back empty.
  //
  // The "Completed by" picker keeps that dead end: it still lists members of helper-only
  // households, and the payload carries no member -> household association to narrow it by.
  // Nothing leaks (those names are already on Home), but do not read this as complete.
  const visible = useMemo(() => householdIdsWithRole(memberships, 'deputy'), [memberships])
  const [options, setOptions] = useState<HistoryFilterOptions>(EMPTY_OPTIONS)
  const [error, setError] = useState<string | null>(null)

  // Latest-value refs so the options effect below can prune a remembered filter
  // without taking them as dependencies (which would refetch the options).
  const setFiltersRef = useRef(table.setFilters)
  const filtersRef = useRef(table.filters)
  useEffect(() => {
    setFiltersRef.current = table.setFilters
    filtersRef.current = table.filters
  })

  // The user/household filter options (and whether to show each filter at all).
  useEffect(() => {
    let cancelled = false
    api
      .get<HistoryFilterOptions>(endpoints.completions.filters)
      .then((data) => {
        if (cancelled) return
        const scoped = { ...data, households: data.households.filter((h) => visible.has(h.id)) }
        setOptions(scoped)
        // A remembered id outlives whatever made it valid (household left, member removed,
        // role dropped below deputy). Left in place it filters the list down to nothing
        // behind a blank Select, so drop what can no longer be picked. Both go in ONE
        // setFilters call: two setFilter calls in a tick would lose the first, see the hook.
        const { household_id, user_id } = filtersRef.current
        const dead: Partial<HistoryFilters> = {}
        if (household_id !== '' && !scoped.households.some((h) => String(h.id) === household_id)) {
          dead.household_id = ''
        }
        if (user_id !== '' && !data.members.some((m) => String(m.id) === user_id)) {
          dead.user_id = ''
        }
        if (Object.keys(dead).length > 0) setFiltersRef.current(dead)
      })
      .catch(() => {
        if (!cancelled) setOptions(EMPTY_OPTIONS)
      })
    return () => {
      cancelled = true
    }
  }, [visible])

  // Undo = delete the completion. The server re-anchors the chore's schedule, so
  // undoing the latest completion makes the chore due again.
  async function undo(entry: HistoryEntry) {
    setError(null)
    try {
      await api.del(endpoints.completions.byId(entry.id))
      toast.success(t('history.undone'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('history.undoError'))
    }
  }

  function undoDialog(entry: HistoryEntry): ReactNode {
    const label = t('history.undo')
    return (
      <AlertDialog>
        <Tooltip>
          <TooltipTrigger asChild>
            <AlertDialogTrigger asChild>
              <Button type="button" variant="ghost" size="icon-sm" aria-label={label}>
                <Undo2Icon />
              </Button>
            </AlertDialogTrigger>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('history.undoConfirm')}</AlertDialogTitle>
            <AlertDialogDescription>{t('history.undoConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void undo(entry)}>
              {t('history.undoConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  const columns: ColumnDef<HistoryEntry>[] = [
    {
      accessorKey: 'title',
      header: t('history.headers.title'),
      // A skip is a closure that produced no work, and without this the row is
      // indistinguishable from real work being logged. Greyed like the Skip button that
      // created it, and beside the title rather than in the lateness column, which is
      // already the `notDue` placeholder for these (the server sends days_late: null).
      cell: ({ row }) => (
        <span className="flex items-center gap-2">
          <span className="font-semibold">{row.original.title}</span>
          {row.original.skipped && (
            <Badge variant="secondary" className="shrink-0 text-muted-foreground">
              {t('history.skipped')}
            </Badge>
          )}
        </span>
      ),
    },
    {
      id: 'household',
      accessorFn: (e) => e.household.name,
      header: t('history.headers.household'),
      enableSorting: false,
      cell: ({ row }) => (
        <span className="font-medium text-muted-foreground">{row.original.household.name}</span>
      ),
    },
    {
      // id matches the server sort key (created_at); the field is completed_at.
      id: 'created_at',
      accessorFn: (e) => e.completed_at,
      header: t('history.headers.completed'),
      cell: ({ row }) => formatDateTime(row.original.completed_at),
      meta: { cellClassName: 'font-medium text-muted-foreground' },
    },
    {
      id: 'overdue',
      header: t('history.headers.overdue'),
      enableSorting: false,
      // null means the chore was unscheduled and so had no deadline to be late against
      // (the server decides that, see HistoryEntryRead). A placeholder rather than "On
      // time", which would claim a punctuality nothing was measuring.
      cell: ({ row }) =>
        row.original.days_late === null ? (
          <span className="text-muted-foreground">{t('history.notDue')}</span>
        ) : row.original.days_late > 0 ? (
          <span className="font-semibold text-danger">
            {t('history.daysLate', { count: row.original.days_late })}
          </span>
        ) : (
          <span className="text-muted-foreground">{t('history.onTime')}</span>
        ),
    },
    {
      id: 'completedBy',
      header: t('history.headers.completedBy'),
      enableSorting: false,
      cell: ({ row }) =>
        row.original.completed_by ? (
          fullName(row.original.completed_by)
        ) : (
          <span className="text-muted-foreground">{t('history.unknownUser')}</span>
        ),
    },
    {
      id: 'actions',
      header: t('history.headers.actions'),
      enableSorting: false,
      // Only the person who recorded a completion may undo it.
      cell: ({ row }) =>
        row.original.completed_by?.id === user?.id ? undoDialog(row.original) : null,
      meta: { headClassName: 'text-right', cellClassName: 'text-right' },
    },
  ]

  return (
    <TooltipProvider>
      <main className="w-full px-5 py-8">
        <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
          {t('history.title')}
        </h1>

        {(error || table.error) && (
          <p className="mb-4 text-[13px] font-bold text-danger">
            {error ?? t('history.loadError')}
          </p>
        )}

        {/* The outcome filter is always available, so the bar renders unconditionally now:
            unlike the two option lists, the server does not tell us whether any skips exist,
            so there is nothing to hide it on. */}
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <Select
            value={table.filters.outcome || ALL}
            onValueChange={(v) => table.setFilter('outcome', v === ALL ? '' : v)}
          >
            <SelectTrigger className="sm:w-56" aria-label={t('history.filters.outcomeLabel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('history.filters.outcomeAll')}</SelectItem>
              <SelectItem value="completed">{t('history.filters.outcomeCompleted')}</SelectItem>
              <SelectItem value="skipped">{t('history.filters.outcomeSkipped')}</SelectItem>
            </SelectContent>
          </Select>
          {options.members.length > 1 && (
            <Select
              value={table.filters.user_id || ALL}
              onValueChange={(v) => table.setFilter('user_id', v === ALL ? '' : v)}
            >
              <SelectTrigger className="sm:w-56" aria-label={t('history.filters.userLabel')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>{t('history.filters.userAll')}</SelectItem>
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
              <SelectTrigger className="sm:w-56" aria-label={t('history.filters.householdLabel')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>{t('history.filters.householdAll')}</SelectItem>
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
          minWidthClassName="min-w-[760px]"
          emptyMessage={t('history.empty')}
        />
      </main>
    </TooltipProvider>
  )
}
