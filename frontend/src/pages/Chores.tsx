import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { CopyPlusIcon, SquarePenIcon, Trash2Icon } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { householdIdsWithRole } from '../lib/permissions'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import { formatDate, formatDateTime, repeatLabel } from '../lib/chores'
import type { Chore, ChoreCloneState, Household, Page } from '../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
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

type ChoreFilters = { household_id: string; title: string }

// Radix Selects can't hold an empty value, so "All households" uses a sentinel
// that maps back to an omitted household_id filter.
const ALL = 'all'

export default function Chores() {
  const { t } = useTranslation()

  const table = useServerTable<Chore, ChoreFilters>({
    endpoint: endpoints.chores.root,
    storageKey: 'chores',
    initial: {
      sortBy: 'created_at',
      sortDir: 'desc',
      pageSize: 10,
      filters: { household_id: '', title: '' },
    },
  })

  const { memberships } = useAuth()
  // Memoised so it is a stable dependency of the load effect below.
  const organised = useMemo(() => householdIdsWithRole(memberships, 'organiser'), [memberships])
  const [households, setHouseholds] = useState<Household[]>([])
  const [error, setError] = useState<string | null>(null)

  // Local text-filter state for instant typing feedback; pushed to the table
  // (which refetches server-side) after a short debounce.
  const [titleInput, setTitleInput] = useState(table.filters.title)

  // Keep a latest-value ref to the (per-render) setFilter so the debounce effect
  // doesn't need it as a dependency (which would reset the timer every render).
  // Same trick for the active filters, so the options effect below can prune a
  // remembered household without re-running (which would refetch the options).
  const setFilterRef = useRef(table.setFilter)
  const filtersRef = useRef(table.filters)
  useEffect(() => {
    setFilterRef.current = table.setFilter
    filtersRef.current = table.filters
  })

  useEffect(() => {
    const id = setTimeout(() => setFilterRef.current('title', titleInput.trim()), 300)
    return () => clearTimeout(id)
  }, [titleInput])

  // The household filter options (and whether to show the filter at all), narrowed to the
  // ones the caller organises - the only ones this list returns chores for.
  useEffect(() => {
    let cancelled = false
    api
      .get<Page<Household>>(`${endpoints.households.root}?sort_by=id&sort_dir=asc&page_size=100`)
      .then((page) => {
        if (cancelled) return
        const mine = page.items.filter((h) => organised.has(h.id))
        setHouseholds(mine)
        // A remembered household_id outlives whatever made it valid (household left,
        // deleted, membership revoked, or the role dropped below organiser). Left in place
        // it filters the list down to nothing behind a blank Select, so drop what can no
        // longer be picked.
        const active = filtersRef.current.household_id
        if (active !== '' && !mine.some((h) => String(h.id) === active)) {
          setFilterRef.current('household_id', '')
        }
      })
      .catch(() => {
        if (!cancelled) setHouseholds([])
      })
    return () => {
      cancelled = true
    }
  }, [organised])

  async function remove(chore: Chore) {
    setError(null)
    try {
      await api.del(endpoints.chores.byId(chore.id))
      toast.success(t('chores.deleted'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('chores.deleteError'))
    }
  }

  function deleteDialog(chore: Chore): ReactNode {
    const label = t('chores.delete')
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
                className="text-destructive hover:text-destructive"
              >
                <Trash2Icon />
              </Button>
            </AlertDialogTrigger>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('chores.deleteConfirm', { title: chore.title })}</AlertDialogTitle>
            <AlertDialogDescription>{t('chores.deleteConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove(chore)}>
              {t('chores.deleteConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  // Clone opens the create page prefilled from this chore, carried in router
  // state. Assignees/tags that don't belong to the chosen household are dropped
  // there (see ChoreCreate); nothing is dropped for a same-household clone.
  function cloneState(chore: Chore): { clone: ChoreCloneState } {
    return {
      clone: {
        household_id: chore.household.id,
        title: chore.title,
        description: chore.description ?? '',
        // '' is the form's spelling of "no start date" (an unscheduled source chore).
        start_date: chore.start_date ?? '',
        repeats: chore.repeats,
        assignment_type: chore.assignment_type,
        turn_length: chore.turn_length,
        repeat_interval: chore.repeat_interval,
        weekdays: chore.weekdays ?? [],
        assignee_ids: chore.assignees.map((a) => a.id),
        tag_ids: chore.tags.map((tag) => tag.id),
      },
    }
  }

  function rowActions(chore: Chore): ReactNode {
    const editLabel = t('chores.edit')
    const cloneLabel = t('chores.clone')
    return (
      <div className="flex items-center justify-end gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button asChild variant="ghost" size="icon-sm" aria-label={editLabel}>
              <Link to={routes.chores.edit.to(chore.id)}>
                <SquarePenIcon />
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{editLabel}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button asChild variant="ghost" size="icon-sm" aria-label={cloneLabel}>
              <Link to={routes.chores.new} state={cloneState(chore)}>
                <CopyPlusIcon />
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{cloneLabel}</TooltipContent>
        </Tooltip>
        {deleteDialog(chore)}
      </div>
    )
  }

  // Keep the tags column compact: show the first tag, then "and N more" with the
  // full list in a tooltip, so a heavily-tagged chore doesn't blow up the row.
  function tagsCell(tags: Chore['tags']): ReactNode {
    if (tags.length === 0) {
      return <span className="text-muted-foreground">{t('chores.noTags')}</span>
    }
    const first = tags[0]
    const extra = tags.length - 1
    if (extra === 0) {
      return (
        <span className="flex items-center gap-1.5 text-[13px] font-semibold">
          <span
            className="inline-block size-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: first.color }}
          />
          {first.name}
        </span>
      )
    }
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-sm text-[13px] font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span
              className="inline-block size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: first.color }}
            />
            {first.name}
            <span className="font-medium text-muted-foreground">
              {t('chores.andMore', { count: extra })}
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent>
          <span className="flex flex-col gap-1.5">
            {tags.map((tag) => (
              <span key={tag.id} className="flex items-center gap-1.5 text-[13px] font-semibold">
                <span
                  className="inline-block size-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: tag.color }}
                />
                {tag.name}
              </span>
            ))}
          </span>
        </TooltipContent>
      </Tooltip>
    )
  }

  const columns: ColumnDef<Chore>[] = [
    {
      accessorKey: 'title',
      header: t('chores.headers.title'),
      cell: ({ row }) => <span className="font-semibold">{row.original.title}</span>,
    },
    {
      id: 'household',
      accessorFn: (c) => c.household.name,
      header: t('chores.headers.household'),
      cell: ({ row }) => (
        <span className="font-medium text-muted-foreground">{row.original.household.name}</span>
      ),
    },
    {
      id: 'assignees',
      header: t('chores.headers.assignees'),
      enableSorting: false,
      cell: ({ row }) =>
        row.original.assignees.length === 0 ? (
          <span className="text-muted-foreground">{t('chores.unassigned')}</span>
        ) : (
          <span className="tabular-nums">{row.original.assignees.length}</span>
        ),
    },
    {
      id: 'repeats',
      header: t('chores.headers.repeats'),
      enableSorting: false,
      cell: ({ row }) => (
        <Badge variant="secondary" className="text-primary">
          {repeatLabel(t, row.original)}
        </Badge>
      ),
    },
    {
      id: 'assignment',
      header: t('chores.headers.assignment'),
      enableSorting: false,
      cell: ({ row }) => {
        const current = row.original.current_assignee
        return (
          <span>
            {t(`options.assignment.${row.original.assignment_type}`)}
            {current && <span className="text-foreground"> · {current.first_name}</span>}
          </span>
        )
      },
      meta: { cellClassName: 'font-medium text-muted-foreground' },
    },
    {
      id: 'tags',
      header: t('chores.headers.tags'),
      enableSorting: false,
      cell: ({ row }) => tagsCell(row.original.tags),
    },
    {
      accessorKey: 'start_date',
      header: t('chores.headers.start'),
      // An unscheduled chore has no start date; the Repeats column beside this one
      // already says so, hence a bare placeholder rather than a second explanation.
      cell: ({ row }) =>
        row.original.start_date ? formatDate(row.original.start_date) : t('chores.noStart'),
      meta: { cellClassName: 'font-medium text-muted-foreground' },
    },
    {
      // Date *and* time, like the History table: chores created on the same day
      // are common, and the whole point of this column is to order by creation.
      accessorKey: 'created_at',
      header: t('chores.headers.createdAt'),
      cell: ({ row }) => formatDateTime(row.original.created_at),
      meta: { cellClassName: 'font-medium text-muted-foreground' },
    },
    {
      id: 'actions',
      header: t('chores.headers.actions'),
      enableSorting: false,
      cell: ({ row }) => rowActions(row.original),
      // Pinned to the right edge (`.pinned-col`) so the buttons stay visible
      // while the other columns scroll under it; the class handles the sticky
      // positioning, opaque background, and the overflow-only left shadow.
      meta: {
        headClassName: 'text-right pinned-col',
        cellClassName: 'text-right pinned-col',
      },
    },
  ]

  return (
    <TooltipProvider>
      <main className="w-full px-5 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold tracking-tight">{t('chores.title')}</h1>
          <Button asChild size="lg">
            <Link to={routes.chores.new}>{t('chores.new')}</Link>
          </Button>
        </div>

        {(error || table.error) && (
          <p className="mb-4 text-[13px] font-bold text-danger">{error ?? t('chores.loadError')}</p>
        )}

        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <Input
            className="sm:w-56"
            placeholder={t('chores.filters.titlePlaceholder')}
            aria-label={t('chores.filters.titlePlaceholder')}
            value={titleInput}
            onChange={(e) => setTitleInput(e.target.value)}
          />
          {households.length > 1 && (
            <Select
              value={table.filters.household_id || ALL}
              onValueChange={(v) => table.setFilter('household_id', v === ALL ? '' : v)}
            >
              <SelectTrigger className="sm:w-56" aria-label={t('chores.filters.householdLabel')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>{t('chores.filters.householdAll')}</SelectItem>
                {households.map((h) => (
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
          minWidthClassName="min-w-[880px]"
          emptyMessage={t('chores.empty')}
        />
      </main>
    </TooltipProvider>
  )
}
