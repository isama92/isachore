import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ColumnDef } from '@tanstack/react-table'
import { api } from '../lib/api'
import { formatDateTime } from '../lib/chores'
import { fullName } from '../lib/user'
import type { HistoryEntry, HistoryFilterOptions } from '../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type HistoryFilters = { user_id: string; household_id: string }

// Radix Selects can't hold an empty value, so the "all" option uses a sentinel
// that maps back to an omitted filter.
const ALL = 'all'

const EMPTY_OPTIONS: HistoryFilterOptions = { households: [], members: [] }

export default function History() {
  const { t } = useTranslation()

  const table = useServerTable<HistoryEntry, HistoryFilters>({
    endpoint: '/api/v1/completions',
    initial: {
      sortBy: 'created_at',
      sortDir: 'desc',
      pageSize: 10,
      filters: { user_id: '', household_id: '' },
    },
  })

  const [options, setOptions] = useState<HistoryFilterOptions>(EMPTY_OPTIONS)

  // The user/household filter options (and whether to show each filter at all).
  useEffect(() => {
    let cancelled = false
    api
      .get<HistoryFilterOptions>('/api/v1/completions/filters')
      .then((data) => {
        if (!cancelled) setOptions(data)
      })
      .catch(() => {
        if (!cancelled) setOptions(EMPTY_OPTIONS)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const columns: ColumnDef<HistoryEntry>[] = [
    {
      accessorKey: 'title',
      header: t('history.headers.title'),
      cell: ({ row }) => <span className="font-semibold">{row.original.title}</span>,
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
      cell: ({ row }) =>
        row.original.days_late > 0 ? (
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
  ]

  return (
    <main className="mx-auto w-full max-w-5xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">{t('history.title')}</h1>

      {table.error && (
        <p className="mb-4 text-[13px] font-bold text-danger">{t('history.loadError')}</p>
      )}

      {(options.members.length > 1 || options.households.length > 1) && (
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
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
        minWidthClassName="min-w-[720px]"
        emptyMessage={t('history.empty')}
      />
    </main>
  )
}
