import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { Trash2Icon } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { householdResource } from '@/lib/endpoints'
import { fullName } from '@/lib/user'
import type { HouseholdMember } from '@/lib/types'
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

type Props = {
  // The household base URL: endpoints are `${basePath}/members` (list) and
  // `${basePath}/members/{id}` (remove).
  basePath: string
  // The owner's user id: badged and never removable (transfer ownership first).
  adminId: number
  // Whether the viewer may remove members (owner or site admin). When false the
  // table is read-only (no actions column).
  canManage: boolean
}

// A household's active members. The owner row is badged and has no remove
// control; adding members is a later feature.
export function HouseholdMembersTable({ basePath, adminId, canManage }: Props) {
  const { t } = useTranslation()
  // No filter UI here (households have few members); the table just paginates.
  const table = useServerTable<HouseholdMember>({
    endpoint: householdResource(basePath).members,
    initial: { sortBy: 'name', sortDir: 'asc', pageSize: 10, filters: {} },
  })
  const [error, setError] = useState<string | null>(null)

  async function remove(member: HouseholdMember) {
    setError(null)
    try {
      await api.del(householdResource(basePath).member(member.id))
      toast.success(t('households.memberRemoved'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.removeMemberError'))
    }
  }

  function removeAction(member: HouseholdMember): ReactNode {
    const label = t('households.removeMember')
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
              {t('households.removeMemberConfirm', { name: fullName(member) })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t('households.removeMemberBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove(member)}>
              {t('households.removeMemberAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  const columns: ColumnDef<HouseholdMember>[] = [
    {
      accessorKey: 'id',
      header: t('households.membersHeaders.id'),
      meta: {
        headClassName: 'w-16',
        cellClassName: 'font-medium text-muted-foreground tabular-nums',
      },
    },
    {
      id: 'name',
      accessorFn: (m) => fullName(m),
      header: t('households.membersHeaders.name'),
      cell: ({ row }) => (
        <span className="flex items-center gap-2 font-semibold">
          {fullName(row.original)}
          {row.original.id === adminId && (
            <Badge variant="secondary" className="text-primary">
              {t('households.adminBadge')}
            </Badge>
          )}
        </span>
      ),
    },
  ]
  if (canManage) {
    columns.push({
      id: 'actions',
      header: t('households.membersHeaders.actions'),
      enableSorting: false,
      // The owner can't be removed (transfer ownership first), so their row has
      // no remove control.
      cell: ({ row }) =>
        row.original.id === adminId ? null : (
          <div className="flex justify-end">{removeAction(row.original)}</div>
        ),
      meta: { headClassName: 'text-right', cellClassName: 'text-right' },
    })
  }

  return (
    <TooltipProvider>
      {error && <p className="mb-3 text-[13px] font-bold text-danger">{error}</p>}
      <DataTable
        columns={columns}
        table={table}
        pageSizeOptions={[10, 20, 50]}
        minWidthClassName="min-w-[380px]"
        emptyMessage={t('households.membersEmpty')}
      />
    </TooltipProvider>
  )
}
