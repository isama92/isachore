import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { CopyPlusIcon, SquarePenIcon, Trash2Icon } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { formatDate } from '../lib/chores'
import type { Chore, ChoreCloneState, Household, Page } from '../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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

type ChoreFilters = { household_id: string }

// Radix Selects can't hold an empty value, so "All households" uses a sentinel
// that maps back to an omitted household_id filter.
const ALL = 'all'

export default function Chores() {
  const { t } = useTranslation()

  const table = useServerTable<Chore, ChoreFilters>({
    endpoint: '/api/v1/chores',
    initial: { sortBy: 'start_date', sortDir: 'asc', pageSize: 10, filters: { household_id: '' } },
  })

  const [households, setHouseholds] = useState<Household[]>([])
  const [error, setError] = useState<string | null>(null)

  // The household filter options (and whether to show the filter at all).
  useEffect(() => {
    let cancelled = false
    api
      .get<Page<Household>>('/api/v1/households?sort_by=id&sort_dir=asc&page_size=100')
      .then((page) => {
        if (!cancelled) setHouseholds(page.items)
      })
      .catch(() => {
        if (!cancelled) setHouseholds([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function remove(chore: Chore) {
    setError(null)
    try {
      await api.del(`/api/v1/chores/${chore.id}`)
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
        start_date: chore.start_date,
        repeats: chore.repeats,
        assignment_type: chore.assignment_type,
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
              <Link to={`/chores/${chore.id}/edit`}>
                <SquarePenIcon />
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{editLabel}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button asChild variant="ghost" size="icon-sm" aria-label={cloneLabel}>
              <Link to="/chores/new" state={cloneState(chore)}>
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
          {t(`options.repeat.${row.original.repeats}`)}
        </Badge>
      ),
    },
    {
      id: 'assignment',
      header: t('chores.headers.assignment'),
      enableSorting: false,
      cell: ({ row }) => t(`options.assignment.${row.original.assignment_type}`),
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
      cell: ({ row }) => formatDate(row.original.start_date),
      meta: { cellClassName: 'font-medium text-muted-foreground' },
    },
    {
      id: 'actions',
      header: t('chores.headers.actions'),
      enableSorting: false,
      cell: ({ row }) => rowActions(row.original),
      meta: { headClassName: 'text-right', cellClassName: 'text-right' },
    },
  ]

  return (
    <TooltipProvider>
      <main className="mx-auto w-full max-w-5xl px-5 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold tracking-tight">{t('chores.title')}</h1>
          <Button asChild size="lg">
            <Link to="/chores/new">{t('chores.new')}</Link>
          </Button>
        </div>

        {(error || table.error) && (
          <p className="mb-4 text-[13px] font-bold text-danger">{error ?? t('chores.loadError')}</p>
        )}

        {households.length > 1 && (
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
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
          </div>
        )}

        <DataTable
          columns={columns}
          table={table}
          minWidthClassName="min-w-[760px]"
          emptyMessage={t('chores.empty')}
        />
      </main>
    </TooltipProvider>
  )
}
