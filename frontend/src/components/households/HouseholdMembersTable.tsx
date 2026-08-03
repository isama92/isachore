import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { Trash2Icon } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { householdResource } from '@/lib/endpoints'
import { fullName } from '@/lib/user'
import { HOUSEHOLD_ROLES, type HouseholdMemberWithRole, type HouseholdRole } from '@/lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
  // Whether the viewer may change roles, which is the household owner and nobody else.
  // A separate prop from canManage rather than the same one: the admin surface passes
  // canManage unconditionally, and it has no member-PATCH endpoint to call. Roles show
  // there as badges, and a site admin who needs to change one impersonates the owner.
  canEditRoles?: boolean
}

// A household's active members and their roles. The owner row is badged, has no remove
// control (transfer ownership first) and no role control (owners are always organisers);
// adding members is a later feature.
export function HouseholdMembersTable({
  basePath,
  adminId,
  canManage,
  canEditRoles = false,
}: Props) {
  const { t } = useTranslation()
  // No filter UI here (households have few members); the table just paginates.
  const table = useServerTable<HouseholdMemberWithRole>({
    endpoint: householdResource(basePath).members,
    // One key for every household, member and admin view alike: what is being
    // remembered is a sort preference, not anything household-specific.
    storageKey: 'household-members',
    initial: { sortBy: 'name', sortDir: 'asc', pageSize: 10, filters: {} },
  })
  const [error, setError] = useState<string | null>(null)

  async function remove(member: HouseholdMemberWithRole) {
    setError(null)
    try {
      await api.del(householdResource(basePath).member(member.id))
      toast.success(t('households.memberRemoved'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.removeMemberError'))
    }
  }

  async function setRole(member: HouseholdMemberWithRole, role: HouseholdRole) {
    setError(null)
    try {
      await api.patch(householdResource(basePath).member(member.id), { role })
      toast.success(t('households.roleUpdated', { name: fullName(member) }))
      table.reload()
    } catch (err) {
      // Reload on failure too. Not to undo the Select, which is controlled by `member.role`
      // and so never moved: to re-read the roster, since the likeliest reason a role change is
      // refused is that this viewer is no longer the owner, and then everything on screen is
      // stale rather than just the one row.
      table.reload()
      setError(err instanceof ApiError ? err.message : t('households.roleError'))
    }
  }

  function roleCell(member: HouseholdMemberWithRole): ReactNode {
    // The owner's role is fixed: they are always an organiser, and the way to change who
    // that is is the household admin select above this table (which promotes the new owner).
    // So their row shows a badge even for a viewer who may edit everyone else's.
    if (!canEditRoles || member.id === adminId) {
      return <Badge variant="secondary">{t(`households.roles.${member.role}`)}</Badge>
    }
    return (
      <Select value={member.role} onValueChange={(v) => void setRole(member, v as HouseholdRole)}>
        <SelectTrigger
          className="w-40"
          aria-label={t('households.roleLabel', { name: fullName(member) })}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {HOUSEHOLD_ROLES.map((role) => (
            <SelectItem key={role} value={role}>
              {t(`households.roles.${role}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  function removeAction(member: HouseholdMemberWithRole): ReactNode {
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

  const columns: ColumnDef<HouseholdMemberWithRole>[] = [
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
    {
      id: 'role',
      header: t('households.membersHeaders.role'),
      // Not sortable: the server's whitelist has no role key, and sorting these
      // alphabetically (deputy, helper, organiser) would imply a ranking that isn't one.
      enableSorting: false,
      cell: ({ row }) => roleCell(row.original),
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
        minWidthClassName="min-w-[520px]"
        emptyMessage={t('households.membersEmpty')}
      />
    </TooltipProvider>
  )
}
