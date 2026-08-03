import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { Trash2Icon } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { householdResource } from '@/lib/endpoints'
import { fullName } from '@/lib/user'
import { assignableRoles } from '@/lib/permissions'
import type { HouseholdMemberWithRole, HouseholdRole } from '@/lib/types'
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
  // The household base URL, user surface or admin: endpoints are `${basePath}/members`
  // (list) and `${basePath}/members/{id}` (PATCH a role, DELETE the membership).
  basePath: string
  // The owner's user id. Their row reads "Admin" in the role column, and is the one row that
  // is never removable (transfer ownership first) and never re-rolable, by anybody.
  adminId: number
  // Whether the viewer may remove members: the household owner, and a site admin. Kept
  // separate from the role props below because the two govern different endpoints, not
  // because one surface lacks one - both have a member DELETE and a member PATCH.
  canManage: boolean
  // Who is looking, for the role controls. Both default to "nobody", which is what keeps a
  // deputy or helper's view read-only without passing anything. `assignableRoles` turns these
  // into the options for a given row.
  //
  // `viewerUnrestricted` covers the household owner AND a site admin on Admin > Households:
  // both may set any of the three. Named for the capability rather than for ownership,
  // because those are two different people with one reach.
  viewerUnrestricted?: boolean
  viewerRole?: HouseholdRole | null
}

// A household's active members and their roles. The owner's row reads "Admin", has no remove
// control (transfer ownership first) and no role control (owners are always organisers);
// adding members happens through an invitation, not here.
export function HouseholdMembersTable({
  basePath,
  adminId,
  canManage,
  viewerUnrestricted = false,
  viewerRole = null,
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
  // The role change awaiting confirmation, or null. Picking in the Select only stages it;
  // nothing is sent until the dialog is accepted. Cancelling needs no revert, because the
  // Select is controlled by `member.role` and that has not moved - the trigger goes on
  // showing the stored role for as long as the dialog is open, which is also the honest
  // thing to show, since at that point nothing has changed.
  const [pending, setPending] = useState<{
    member: HouseholdMemberWithRole
    role: HouseholdRole
  } | null>(null)

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
    const targetIsOwner = member.id === adminId
    // The owner's cell reads "Admin", not "Organiser". They are one, but saying so here
    // duplicates the fact that matters and buries it: one household admin, and their role is
    // the one thing on this table nobody can change.
    if (targetIsOwner) {
      return <Badge variant="secondary">{t('households.adminRole')}</Badge>
    }
    const options = assignableRoles({
      viewerUnrestricted,
      viewerRole,
      targetIsOwner,
      targetRole: member.role,
    })
    // No options means no control: a deputy or helper looking, the admin surface, or an
    // organiser looking at a peer organiser.
    if (options.length === 0) {
      return <Badge variant="secondary">{t(`households.roles.${member.role}`)}</Badge>
    }
    return (
      <Select
        value={member.role}
        onValueChange={(v) => {
          // Radix does not fire this for the already-selected item, so the guard is belt and
          // braces rather than load-bearing - but a confirm dialog for "no change" would be
          // pure noise if it ever did.
          const role = v as HouseholdRole
          if (role !== member.role) setPending({ member, role })
        }}
      >
        <SelectTrigger
          className="w-40"
          aria-label={t('households.roleLabel', { name: fullName(member) })}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((role) => (
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
      // No badge beside the name: the role column says "Admin" for this row, and saying it
      // twice made the table read as if those were two different facts.
      cell: ({ row }) => <span className="font-semibold">{fullName(row.original)}</span>,
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
      {/* Controlled, and rendered once for the table rather than per row: `onValueChange` is
          not a trigger click, so there is nothing for an AlertDialogTrigger to wrap. */}
      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('households.roleConfirm', {
                name: pending ? fullName(pending.member) : '',
                role: pending ? t(`households.roles.${pending.role}`) : '',
              })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t('households.roleConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pending) void setRole(pending.member, pending.role)
              }}
            >
              {t('households.roleConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
