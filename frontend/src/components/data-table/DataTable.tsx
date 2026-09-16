import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  columnVisibilityFeature,
  createCoreRowModel,
  flexRender,
  rowPaginationFeature,
  rowSortingFeature,
  tableFeatures,
  useTable,
  type CellData,
  type ColumnDef,
  type OnChangeFn,
  type PaginationState,
  type RowData,
  type SortingState,
  type TableFeatures,
} from '@tanstack/react-table'
import { useTranslation } from 'react-i18next'
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import type { FilterSet, UseServerTableResult } from './useServerTable'

// Per-column presentation hooks, set on a column's `meta`. Keeps the generic
// table free of any column-specific styling.
//
// The parameter list has to match table-core's own `ColumnMeta` declaration
// exactly, variance annotations included, or the merge is rejected outright
// rather than merely losing these two fields.
declare module '@tanstack/react-table' {
  /* eslint-disable @typescript-eslint/no-unused-vars */
  interface ColumnMeta<
    in out TFeatures extends TableFeatures,
    in out TData extends RowData,
    TValue extends CellData = CellData,
  > {
    headClassName?: string
    cellClassName?: string
  }
  /* eslint-enable @typescript-eslint/no-unused-vars */
}

// Features are opt-in, and a method a feature owns does not exist on the table
// without it: `getVisibleCells` comes from column visibility, the sort handlers
// from row sorting. The row models are deliberately absent — the server sorts
// and paginates, so a client-side model here would reorder the page it was
// handed. Filtering has no feature at all: it lives entirely in the URL and the
// request, and never reaches the table.
const dataTableFeatures = tableFeatures({
  columnVisibilityFeature,
  rowPaginationFeature,
  rowSortingFeature,
  coreRowModel: createCoreRowModel(),
})

// Pages declare their own columns, so they need the feature set the table is
// actually built with; spelling the generic out at each call site would leak
// this module's internals into all eight of them.
export type DataTableColumn<Row extends RowData> = ColumnDef<typeof dataTableFeatures, Row>

const DEFAULT_PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

type DataTableProps<Row extends RowData, Filters extends FilterSet> = {
  columns: DataTableColumn<Row>[]
  table: UseServerTableResult<Row, Filters>
  pageSizeOptions?: number[]
  // A node, not just a string, so a first-run empty state can be more than one
  // line. Every string caller keeps working, a string being a ReactNode.
  emptyMessage?: ReactNode
  // Minimum table width so columns don't crush on narrow viewports; the card
  // scrolls horizontally instead (matches the app's other tables).
  minWidthClassName?: string
}

export function DataTable<Row extends RowData, Filters extends FilterSet>({
  columns,
  table: controller,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  emptyMessage,
  minWidthClassName = 'min-w-[720px]',
}: DataTableProps<Row, Filters>) {
  const { t } = useTranslation()

  const sorting: SortingState = [{ id: controller.sortBy, desc: controller.sortDir === 'desc' }]
  const pagination: PaginationState = {
    pageIndex: controller.page - 1,
    pageSize: controller.pageSize,
  }

  const onSortingChange: OnChangeFn<SortingState> = (updater) => {
    const next = typeof updater === 'function' ? updater(sorting) : updater
    const first = next[0]
    if (first) controller.setSort(first.id, first.desc ? 'desc' : 'asc')
  }

  const table = useTable({
    features: dataTableFeatures,
    data: controller.rows,
    columns,
    manualPagination: true,
    manualSorting: true,
    enableSortingRemoval: false,
    pageCount: controller.pageCount,
    state: { sorting, pagination },
    onSortingChange,
  })

  const rows = table.getRowModel().rows
  const colCount = columns.length

  // Track whether the table overflows its scroll container horizontally, so a
  // pinned column can show a shadow only while there is content under it. The
  // ResizeObserver delivers an initial measurement asynchronously after
  // observe(), so setState never runs synchronously in the effect body.
  const containerRef = useRef<HTMLDivElement>(null)
  const [overflowing, setOverflowing] = useState(false)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => setOverflowing(el.scrollWidth > el.clientWidth)
    const observer = new ResizeObserver(update)
    observer.observe(el)
    // Also watch the inner table: its width can change (e.g. unusually long
    // content) without the container resizing, which would otherwise leave the
    // shadow stale.
    const inner = el.querySelector('table')
    if (inner) observer.observe(inner)
    return () => observer.disconnect()
  }, [])

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-card">
      <Table
        className={minWidthClassName}
        containerRef={containerRef}
        data-overflowing={overflowing}
      >
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id} className="hover:bg-transparent">
              {headerGroup.headers.map((header) => {
                const canSort = header.column.getCanSort()
                const sorted = header.column.getIsSorted()
                return (
                  <TableHead
                    key={header.id}
                    className={header.column.columnDef.meta?.headClassName}
                    aria-sort={
                      canSort
                        ? sorted === 'asc'
                          ? 'ascending'
                          : sorted === 'desc'
                            ? 'descending'
                            : 'none'
                        : undefined
                    }
                  >
                    {header.isPlaceholder ? null : canSort ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="-ml-2.5 h-8 gap-1.5 px-2.5 text-[11.5px] font-bold tracking-wide text-muted-foreground uppercase hover:text-foreground data-[sorted=true]:text-foreground"
                        data-sorted={sorted !== false}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === 'asc' ? (
                          <ArrowUpIcon />
                        ) : sorted === 'desc' ? (
                          <ArrowDownIcon />
                        ) : (
                          <ArrowUpDownIcon className="opacity-50" />
                        )}
                      </Button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody className={cn(controller.loading && 'opacity-60 transition-opacity')}>
          {rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={colCount} className="h-24 text-center text-muted-foreground">
                {controller.loading ? t('common.loading') : (emptyMessage ?? t('table.noResults'))}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className={cell.column.columnDef.meta?.cellClassName}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      <div className="flex flex-col gap-3 border-t border-line px-4 py-3 text-[13px] font-medium text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <span>{t('table.rowsPerPage')}</span>
          <Select
            value={String(controller.pageSize)}
            onValueChange={(value) => controller.setPageSize(Number(value))}
          >
            <SelectTrigger size="sm" className="w-[4.5rem]" aria-label={t('table.rowsPerPage')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pageSizeOptions.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-4">
          <span className="tabular-nums">{t('table.total', { count: controller.total })}</span>
          <span className="tabular-nums">
            {t('table.pageOf', { page: controller.page, pages: controller.pageCount })}
          </span>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label={t('table.previous')}
              disabled={controller.page <= 1}
              onClick={() => controller.setPage(controller.page - 1)}
            >
              <ChevronLeftIcon />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label={t('table.next')}
              disabled={controller.page >= controller.pageCount}
              onClick={() => controller.setPage(controller.page + 1)}
            >
              <ChevronRightIcon />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
