import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { ArchiveRestoreIcon, SquarePenIcon, Trash2Icon } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { endpoints } from '../../lib/endpoints'
import { routes } from '../../lib/routes'
import { formatDateTime, formatDateTimeFull } from '../../lib/format'
import type { Household } from '../../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import { Badge } from '@/components/ui/badge'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

type HouseholdFilters = { name: string; status: string }

export default function AdminHouseholds() {
  const { t } = useTranslation()

  const table = useServerTable<Household, HouseholdFilters>({
    endpoint: endpoints.adminHouseholds.root,
    storageKey: 'admin-households',
    initial: {
      sortBy: 'created_at',
      sortDir: 'desc',
      pageSize: 10,
      filters: { name: '', status: 'active' },
    },
  })

  const [error, setError] = useState<string | null>(null)
  const [nameInput, setNameInput] = useState(table.filters.name)

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
      await api.del(endpoints.adminHouseholds.byId(household.id))
      toast.success(t('households.deleted'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.deleteError'))
    }
  }

  async function restore(household: Household) {
    setError(null)
    try {
      await api.post(endpoints.adminHouseholds.restore(household.id))
      toast.success(t('households.restored'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.restoreError'))
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

  function restoreDialog(household: Household): ReactNode {
    const label = t('households.restore')
    return (
      <AlertDialog>
        <Tooltip>
          <TooltipTrigger asChild>
            <AlertDialogTrigger asChild>
              <Button type="button" variant="ghost" size="icon-sm" aria-label={label}>
                <ArchiveRestoreIcon />
              </Button>
            </AlertDialogTrigger>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('households.restoreConfirm', { name: household.name })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t('households.restoreConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void restore(household)}>
              {t('households.restoreConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  function rowActions(household: Household): ReactNode {
    return (
      <div className="flex items-center justify-end gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button asChild variant="ghost" size="icon-sm" aria-label={t('households.editAction')}>
              <Link to={routes.admin.households.edit.to(household.id)}>
                <SquarePenIcon />
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('households.editAction')}</TooltipContent>
        </Tooltip>
        {household.deleted_at ? restoreDialog(household) : deleteDialog(household)}
      </div>
    )
  }

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
      id: 'status',
      header: t('households.headers.status'),
      enableSorting: false,
      cell: ({ row }) =>
        row.original.deleted_at ? (
          <Badge variant="destructive">{t('households.statusDeleted')}</Badge>
        ) : (
          <Badge variant="secondary" className="text-primary">
            {t('households.statusActive')}
          </Badge>
        ),
    },
    {
      accessorKey: 'created_at',
      header: t('households.headers.createdAt'),
      // Deliberately the viewer's zone, NOT the row's, which is the opposite of the same cell on
      // the user-facing Households page (see the comment there). This is an operator view over
      // households they are not in: reading 50 rows against 50 different clocks is worse than
      // reading them all against one. Do not "fix" this to match without reading both.
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
            <Link to={routes.admin.households.new}>{t('households.add')}</Link>
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
          <Select value={table.filters.status} onValueChange={(v) => table.setFilter('status', v)}>
            <SelectTrigger className="sm:w-44" aria-label={t('households.filters.statusLabel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="active">{t('households.statusActive')}</SelectItem>
              <SelectItem value="deleted">{t('households.statusDeleted')}</SelectItem>
              <SelectItem value="all">{t('households.filters.statusAll')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <DataTable columns={columns} table={table} minWidthClassName="min-w-[820px]" />
      </main>
    </TooltipProvider>
  )
}
