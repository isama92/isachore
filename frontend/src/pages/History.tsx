import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { Undo2Icon } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { hasRoleIn, hasRoleSomewhere } from '../lib/permissions'
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

  // Whether there is anything to slice. A helper everywhere gets their own closures and
  // nothing else, so every filter would be a Select of one option over a list that is
  // already as narrow as it goes: no bar at all is the honest answer. Reaching deputy in one
  // household is enough to keep the whole bar, since that household does have housemates'
  // rows in it.
  const showFilters = hasRoleSomewhere(memberships, 'deputy')
  const [options, setOptions] = useState<HistoryFilterOptions>(EMPTY_OPTIONS)
  const [error, setError] = useState<string | null>(null)

  // The error banner sits above the filter bar, so on a page of rows an undo failing near the
  // bottom reports itself entirely off-screen - and for a helper the bar above it is gone, so
  // it sits higher still. Undo used to be offered on the caller's own rows alone; an organiser
  // now gets it on every row of the household, which is what makes that reachable. Same
  // ref-plus-effect as Chores: `nearest` does nothing when the banner is already in view, and
  // role="alert" covers what scrolling cannot, telling assistive tech wherever it sits.
  const errorRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (error || table.error) errorRef.current?.scrollIntoView({ block: 'nearest' })
  }, [error, table.error])

  // Latest-value refs so the options effect below can prune a remembered filter
  // without taking them as dependencies (which would refetch the options).
  const setFiltersRef = useRef(table.setFilters)
  const filtersRef = useRef(table.filters)
  useEffect(() => {
    setFiltersRef.current = table.setFilters
    filtersRef.current = table.filters
  })

  // The user/household filter options (and whether to show each filter at all). Fetched even
  // when the bar is hidden, so that every setState stays inside .then()/.catch() (the
  // set-state-in-effect rule) and the prune below has one definition rather than two.
  useEffect(() => {
    let cancelled = false

    // Drop a remembered filter that can no longer be picked. `offered` is null when the
    // options request failed, i.e. we cannot tell whether an id is dead - but the hidden-bar
    // case does not depend on the payload at all, which is why this runs on BOTH paths: on a
    // failed fetch a helper would otherwise keep filters applied with no Select on screen to
    // clear them and no error text, and the hook only forgets storage on a 400/422 while
    // these merely return fewer rows. Everything goes in ONE setFilters call: two setFilter
    // calls in a tick would lose the first, see the hook.
    function prune(offered: HistoryFilterOptions | null) {
      const { household_id, user_id, outcome } = filtersRef.current
      const dead: Partial<HistoryFilters> = {}
      if (!showFilters) {
        // A demotion to helper-everywhere leaves all three unreachable - the same trap Tags
        // has with a dead household_id, and here there is not even a Select to blame.
        if (household_id !== '') dead.household_id = ''
        if (user_id !== '') dead.user_id = ''
        if (outcome !== '') dead.outcome = ''
      } else if (offered !== null) {
        // A remembered id outlives whatever made it valid (household left, member removed).
        // Left in place it filters the list down to nothing behind a blank Select.
        if (household_id !== '' && !offered.households.some((h) => String(h.id) === household_id)) {
          dead.household_id = ''
        }
        if (user_id !== '' && !offered.members.some((m) => String(m.id) === user_id)) {
          dead.user_id = ''
        }
      }
      if (Object.keys(dead).length > 0) setFiltersRef.current(dead)
    }

    api
      .get<HistoryFilterOptions>(endpoints.completions.filters)
      .then((data) => {
        if (cancelled) return
        // Not narrowed to deputy households: a household the caller is only a helper in now
        // yields their OWN closures, so every household this payload lists is a live option.
        //
        // The "Completed by" picker keeps its known dead end: it lists members of helper-only
        // households, where only the caller's own rows exist, and the payload carries no
        // member -> household association to narrow it by. Nothing leaks (those names are
        // already on Home), but do not read this as complete.
        setOptions(data)
        prune(data)
      })
      .catch(() => {
        if (cancelled) return
        setOptions(EMPTY_OPTIONS)
        prune(null)
      })
    return () => {
      cancelled = true
    }
  }, [showFilters])

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

  function undoDialog(entry: HistoryEntry, mine: boolean): ReactNode {
    // Somebody else's closure reads as a warning: an organiser removing a housemate's record
    // of work done is a different act from undoing your own, and nothing else in the row says
    // so. A closure whose completer no longer has an account is that same case with no name
    // to put in the copy, so it gets its own wording rather than "Undo Unknown's entry".
    const who = entry.completed_by ? fullName(entry.completed_by) : null
    const label = mine
      ? t('history.undo')
      : who === null
        ? t('history.undoUnknown')
        : t('history.undoOther', { name: who })
    const body = mine
      ? t('history.undoConfirmBody')
      : who === null
        ? t('history.undoUnknownConfirmBody')
        : t('history.undoOtherConfirmBody', { name: who })
    return (
      <AlertDialog>
        <Tooltip>
          <TooltipTrigger asChild>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={label}
                // The hover pair, not just the colour: ghost's own hover would otherwise win
                // it back on the one row where the colour is the whole point.
                className={mine ? undefined : 'text-warning hover:text-warning'}
              >
                <Undo2Icon />
              </Button>
            </AlertDialogTrigger>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
        <AlertDialogContent>
          <AlertDialogHeader>
            {/* Title and confirm action stay shared; whose closure it is belongs in the body,
                so there is still one confirm affordance to find. Nor is the action turned
                destructive-red, which would contradict the peach the row just used. */}
            <AlertDialogTitle>{t('history.undoConfirm')}</AlertDialogTitle>
            <AlertDialogDescription>{body}</AlertDialogDescription>
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
      cell: ({ row }) => formatDateTime(row.original.completed_at, row.original.household.timezone),
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
      // The person a closure is recorded against, or an organiser of that household. Mirrors
      // the API's own disjunction, which re-checks it: this only decides whether to offer a
      // control, never whether the undo is allowed. Written out rather than
      // `completed_by?.id === user?.id` because `mine` now picks the copy and the colour as
      // well as the visibility, and a row whose completer no longer has an account (null) is
      // exactly the case that has to come out as somebody else's rather than as nobody's.
      cell: ({ row }) => {
        const entry = row.original
        const mine =
          user !== null && entry.completed_by !== null && entry.completed_by.id === user.id
        const canUndo = mine || hasRoleIn(memberships, entry.household.id, 'organiser')
        return canUndo ? undoDialog(entry, mine) : null
      },
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
          <p ref={errorRef} role="alert" className="mb-4 text-[13px] font-bold text-danger">
            {error ?? t('history.loadError')}
          </p>
        )}

        {/* The bar as a whole is for anyone who reaches deputy somewhere (see showFilters).
            Within it, the outcome filter is always available: unlike the two option lists, the
            server does not tell us whether any skips exist, so there is nothing to hide it
            on. */}
        {showFilters && (
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
        )}

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
