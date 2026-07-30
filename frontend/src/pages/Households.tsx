import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { EyeIcon, SquarePenIcon, Trash2Icon } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import { formatDateTime, formatDateTimeFull } from '../lib/format'
import type { Household } from '../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import { Button } from '@/components/ui/button'
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

type HouseholdFilters = { name: string }

export default function Households() {
  const { t } = useTranslation()
  const { user: me } = useAuth()

  const table = useServerTable<Household, HouseholdFilters>({
    endpoint: endpoints.households.root,
    storageKey: 'households',
    initial: { sortBy: 'created_at', sortDir: 'desc', pageSize: 10, filters: { name: '' } },
  })

  const [error, setError] = useState<string | null>(null)
  const [nameInput, setNameInput] = useState(table.filters.name)

  // Latest-value ref to the per-render setFilter so the debounce effect doesn't
  // depend on it (which would reset the timer every render).
  const setFilterRef = useRef(table.setFilter)
  useEffect(() => {
    setFilterRef.current = table.setFilter
  })
  useEffect(() => {
    const id = setTimeout(() => setFilterRef.current('name', nameInput.trim()), 300)
    return () => clearTimeout(id)
  }, [nameInput])

  async function remove(household: Household) {
    setError(null)
    try {
      await api.del(endpoints.households.byId(household.id))
      toast.success(t('households.deleted'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.deleteError'))
    }
  }

  function deleteDialog(household: Household): ReactNode {
    const label = t('households.delete')
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
            <AlertDialogTitle>
              {t('households.deleteConfirm', { name: household.name })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t('households.deleteConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove(household)}>
              {t('households.deleteConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  function rowActions(household: Household): ReactNode {
    // Only the owner may edit/delete; other members get a read-only View.
    const owned = me?.id === household.admin_id
    const label = owned ? t('households.editAction') : t('households.view')
    return (
      <div className="flex items-center justify-end gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button asChild variant="ghost" size="icon-sm" aria-label={label}>
              <Link to={routes.households.edit.to(household.id)}>
                {owned ? <SquarePenIcon /> : <EyeIcon />}
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
        {owned && deleteDialog(household)}
      </div>
    )
  }

  // The first-run state, now that nothing provisions a household on sign-up. Both
  // guards earn their place, because an empty page is not the same as an empty
  // account: with a name filter typed in it means no matches, and with `total`
  // above zero it means an out-of-range page (useServerTable deliberately does not
  // clamp `page`, so deleting the last row of page 2 lands here). Claiming "no
  // households yet" above a footer reading "10 total" would be a plain lie.
  const emptyMessage =
    table.filters.name || table.total > 0 ? undefined : (
      <div className="flex flex-col gap-1">
        <span className="font-semibold text-foreground">{t('households.emptyTitle')}</span>
        <span>{t('households.emptyHint')}</span>
      </div>
    )

  const columns: ColumnDef<Household>[] = [
    {
      accessorKey: 'id',
      header: t('households.headers.id'),
      meta: {
        headClassName: 'w-16',
        cellClassName: 'font-medium text-muted-foreground tabular-nums',
      },
    },
    {
      id: 'name',
      accessorFn: (h) => h.name,
      header: t('households.headers.name'),
      cell: ({ row }) => <span className="font-semibold">{row.original.name}</span>,
    },
    {
      id: 'member_count',
      header: t('households.headers.members'),
      enableSorting: false,
      cell: ({ row }) => row.original.member_count,
      meta: { cellClassName: 'tabular-nums text-muted-foreground' },
    },
    {
      id: 'chore_count',
      header: t('households.headers.chores'),
      enableSorting: false,
      cell: ({ row }) => row.original.chore_count,
      meta: { cellClassName: 'tabular-nums text-muted-foreground' },
    },
    {
      accessorKey: 'created_at',
      header: t('households.headers.createdAt'),
      cell: ({ row }) => (
        <span title={formatDateTimeFull(row.original.created_at)}>
          {formatDateTime(row.original.created_at)}
        </span>
      ),
      meta: { cellClassName: 'text-muted-foreground' },
    },
    {
      id: 'actions',
      header: t('households.headers.actions'),
      enableSorting: false,
      cell: ({ row }) => rowActions(row.original),
      meta: { headClassName: 'text-right', cellClassName: 'text-right' },
    },
  ]

  return (
    <TooltipProvider>
      <main className="w-full px-5 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold tracking-tight">
            {t('households.title')}
          </h1>
          <Button asChild size="lg">
            <Link to={routes.households.new}>{t('households.add')}</Link>
          </Button>
        </div>

        {(error || table.error) && (
          <p className="mb-4 text-[13px] font-bold text-danger">
            {error ?? t('households.loadError')}
          </p>
        )}

        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <Input
            className="sm:w-56"
            placeholder={t('households.filters.namePlaceholder')}
            aria-label={t('households.filters.namePlaceholder')}
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
          />
        </div>

        <DataTable
          columns={columns}
          table={table}
          emptyMessage={emptyMessage}
          minWidthClassName="min-w-[720px]"
        />
      </main>
    </TooltipProvider>
  )
}
