import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ColumnDef } from '@tanstack/react-table'
import { renderWithProviders } from '../../test/utils'
import { DataTable } from './DataTable'
import type { UseServerTableResult } from './useServerTable'

type Row = { id: number; name: string; role: string }

const columns: ColumnDef<Row>[] = [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'role', header: 'Role', enableSorting: false },
]

function makeController(
  overrides: Partial<UseServerTableResult<Row, Record<string, string>>> = {},
): UseServerTableResult<Row, Record<string, string>> {
  return {
    rows: [
      { id: 1, name: 'Alice', role: 'Admin' },
      { id: 2, name: 'Bob', role: 'Member' },
    ],
    total: 2,
    loading: false,
    error: null,
    page: 1,
    pageSize: 20,
    sortBy: 'name',
    sortDir: 'asc',
    filters: {},
    pageCount: 1,
    setPage: vi.fn(),
    setPageSize: vi.fn(),
    setSort: vi.fn(),
    setFilter: vi.fn(),
    setFilters: vi.fn(),
    reload: vi.fn(),
    ...overrides,
  }
}

describe('DataTable', () => {
  it('renders a row per item', () => {
    renderWithProviders(<DataTable columns={columns} table={makeController()} />)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
  })

  it('clicking a sortable header toggles the sort direction via the controller', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const controller = makeController() // sorted by name asc
    renderWithProviders(<DataTable columns={columns} table={controller} />)

    await user.click(screen.getByRole('button', { name: /name/i }))
    expect(controller.setSort).toHaveBeenCalledWith('name', 'desc')
  })

  it('does not render a sort control for a non-sortable column', () => {
    renderWithProviders(<DataTable columns={columns} table={makeController()} />)
    const roleHeader = screen.getByRole('columnheader', { name: 'Role' })
    expect(within(roleHeader).queryByRole('button')).toBeNull()
  })

  it('disables previous on the first page and pages forward via the controller', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const controller = makeController({ page: 1, pageCount: 3 })
    renderWithProviders(<DataTable columns={columns} table={controller} />)

    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
    const next = screen.getByRole('button', { name: 'Next page' })
    expect(next).toBeEnabled()
    await user.click(next)
    expect(controller.setPage).toHaveBeenCalledWith(2)
  })

  it('disables next on the last page', () => {
    const controller = makeController({ page: 3, pageCount: 3 })
    renderWithProviders(<DataTable columns={columns} table={controller} />)
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeEnabled()
  })

  it('changing rows-per-page calls the controller', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const controller = makeController()
    renderWithProviders(<DataTable columns={columns} table={controller} />)

    const select = screen.getByRole('combobox', { name: 'Rows per page' })
    expect(select).toHaveTextContent('20')
    await user.click(select)
    await user.click(await screen.findByRole('option', { name: '50' }))
    expect(controller.setPageSize).toHaveBeenCalledWith(50)
  })

  it('shows the empty message when there are no rows', () => {
    renderWithProviders(
      <DataTable columns={columns} table={makeController({ rows: [], total: 0, pageCount: 1 })} />,
    )
    expect(screen.getByText('No results.')).toBeInTheDocument()
  })

  it('shows a loading state while fetching the first page', () => {
    renderWithProviders(
      <DataTable
        columns={columns}
        table={makeController({ rows: [], total: 0, loading: true, pageCount: 1 })}
      />,
    )
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })
})
