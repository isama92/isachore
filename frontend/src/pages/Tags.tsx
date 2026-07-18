import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { SquarePenIcon, Trash2Icon } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import type { Household, Page, Tag } from '../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
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

type TagFilters = { household_id: string }

export default function Tags() {
  const { t } = useTranslation()

  // Tags are always scoped to one household. An empty household_id lets the
  // backend fall back to the caller's current (lowest-id) household; the
  // selector below narrows to a specific one when the user has more than one.
  const table = useServerTable<Tag, TagFilters>({
    endpoint: endpoints.tags.root,
    initial: { sortBy: 'name', sortDir: 'asc', pageSize: 10, filters: { household_id: '' } },
  })

  const [households, setHouseholds] = useState<Household[]>([])
  const [householdsLoaded, setHouseholdsLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Households for the selector (and to know the default the backend falls to).
  useEffect(() => {
    let cancelled = false
    api
      .get<Page<Household>>(`${endpoints.households.root}?sort_by=id&sort_dir=asc&page_size=100`)
      .then((page) => {
        if (!cancelled) setHouseholds(page.items)
      })
      .catch(() => {
        if (!cancelled) setHouseholds([])
      })
      .finally(() => {
        if (!cancelled) setHouseholdsLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function remove(tag: Tag) {
    setError(null)
    try {
      await api.del(endpoints.tags.byId(tag.id))
      toast.success(t('tags.deleted'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('tags.deleteError'))
    }
  }

  function deleteDialog(tag: Tag): ReactNode {
    const label = t('tags.delete')
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
            <AlertDialogTitle>{t('tags.deleteConfirm', { name: tag.name })}</AlertDialogTitle>
            <AlertDialogDescription>{t('tags.deleteConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove(tag)}>
              {t('tags.deleteConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  function rowActions(tag: Tag): ReactNode {
    const editLabel = t('tags.edit')
    return (
      <div className="flex items-center justify-end gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button asChild variant="ghost" size="icon-sm" aria-label={editLabel}>
              <Link to={routes.tags.edit.to(tag.id)}>
                <SquarePenIcon />
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{editLabel}</TooltipContent>
        </Tooltip>
        {deleteDialog(tag)}
      </div>
    )
  }

  const columns: ColumnDef<Tag>[] = [
    {
      accessorKey: 'name',
      header: t('tags.headers.name'),
      cell: ({ row }) => (
        <span className="flex items-center gap-2.5 font-semibold">
          <span
            className="inline-block size-3 rounded-full"
            style={{ backgroundColor: row.original.color }}
          />
          {row.original.name}
        </span>
      ),
    },
    {
      id: 'actions',
      header: t('tags.headers.actions'),
      enableSorting: false,
      cell: ({ row }) => rowActions(row.original),
      meta: { headClassName: 'text-right', cellClassName: 'text-right' },
    },
  ]

  return (
    <TooltipProvider>
      <main className="mx-auto w-full max-w-3xl px-5 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold tracking-tight">{t('tags.title')}</h1>
          <Button asChild size="lg">
            <Link to={routes.tags.new}>{t('tags.new')}</Link>
          </Button>
        </div>

        {householdsLoaded && households.length === 0 ? (
          // The list endpoint needs a household; a member of none can't use it.
          <p className="font-medium text-muted-foreground">{t('tags.noHouseholds')}</p>
        ) : (
          <>
            {(error || table.error) && (
              <p className="mb-4 text-[13px] font-bold text-danger">
                {error ?? t('tags.loadError')}
              </p>
            )}

            {households.length > 1 && (
              <div className="mb-4 flex flex-col gap-1.5">
                <Label id="household-label" htmlFor="household">
                  {t('tags.filters.householdLabel')}
                </Label>
                <Select
                  value={table.filters.household_id || String(households[0]?.id ?? '')}
                  onValueChange={(v) => table.setFilter('household_id', v)}
                >
                  <SelectTrigger
                    id="household"
                    aria-label={t('tags.filters.householdLabel')}
                    className="sm:w-56"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
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
              minWidthClassName="min-w-[420px]"
              emptyMessage={t('tags.empty')}
            />
          </>
        )}
      </main>
    </TooltipProvider>
  )
}
