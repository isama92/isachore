import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { CopyIcon, Trash2Icon, UserPlusIcon } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { householdResource } from '@/lib/endpoints'
import { formatDateTimeFull } from '@/lib/format'
import type { HouseholdInvitation } from '@/lib/types'
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

// Kept in sync with MAX_PENDING_INVITATIONS on the backend.
const MAX_PENDING = 5

// A pending invite is the only revocable/copyable one, and the only kind that
// counts toward the pending limit. Expiry is a stored status now (the backend
// sweep flips pending -> expired), so this just reads `status`.
function isLivePending(invitation: HouseholdInvitation): boolean {
  return invitation.status === 'pending'
}

// The household owner's invitation manager: mint a single-use link ("Add
// member"), copy/revoke live invites, delete the rest (accepted/revoked/
// expired). `basePath` is the household base URL. Only mounted for the owner.
export function HouseholdInvitations({ basePath }: { basePath: string }) {
  const { t } = useTranslation()
  const [invitations, setInvitations] = useState<HouseholdInvitation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .get<HouseholdInvitation[]>(householdResource(basePath).invitations)
      .then((data) => {
        if (!cancelled) setInvitations(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t('households.inviteLoadError'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [basePath, t])

  async function add() {
    setError(null)
    setCreating(true)
    try {
      const invitation = await api.post<HouseholdInvitation>(
        householdResource(basePath).invitations,
      )
      setInvitations((prev) => [invitation, ...prev])
      toast.success(t('households.inviteCreated'))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.inviteError'))
    } finally {
      setCreating(false)
    }
  }

  async function copy(invitation: HouseholdInvitation) {
    if (!navigator.clipboard) {
      setError(t('households.copyError'))
      return
    }
    try {
      await navigator.clipboard.writeText(invitation.url)
      toast.success(t('households.inviteCopied'))
    } catch {
      setError(t('households.copyError'))
    }
  }

  async function revoke(invitation: HouseholdInvitation) {
    setError(null)
    try {
      const updated = await api.post<HouseholdInvitation>(
        householdResource(basePath).revokeInvitation(invitation.id),
      )
      // Keep the row, now shown as revoked (and thus deletable).
      setInvitations((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
      toast.success(t('households.inviteRevoked'))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.inviteError'))
    }
  }

  async function remove(invitation: HouseholdInvitation) {
    setError(null)
    try {
      await api.del(householdResource(basePath).invitation(invitation.id))
      setInvitations((prev) => prev.filter((i) => i.id !== invitation.id))
      toast.success(t('households.inviteRemoved'))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.inviteError'))
    }
  }

  function statusBadge(invitation: HouseholdInvitation): ReactNode {
    switch (invitation.status) {
      case 'accepted':
        return (
          <Badge variant="secondary" className="text-primary">
            {t('households.statusAccepted')}
          </Badge>
        )
      case 'revoked':
        return <Badge variant="destructive">{t('households.statusRevoked')}</Badge>
      case 'expired':
        return (
          <Badge variant="secondary" className="text-muted-foreground">
            {t('households.statusExpired')}
          </Badge>
        )
      default:
        return (
          <Badge variant="secondary" className="text-warning">
            {t('households.statusPending')}
          </Badge>
        )
    }
  }

  function deleteAction(invitation: HouseholdInvitation): ReactNode {
    const label = t('households.inviteDelete')
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            className="text-destructive hover:text-destructive"
            onClick={() => void remove(invitation)}
          >
            <Trash2Icon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    )
  }

  function copyAction(invitation: HouseholdInvitation): ReactNode {
    const label = t('households.inviteCopy')
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            onClick={() => void copy(invitation)}
          >
            <CopyIcon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    )
  }

  function revokeAction(invitation: HouseholdInvitation): ReactNode {
    const label = t('households.inviteRevoke')
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
            <AlertDialogTitle>{t('households.inviteRevokeConfirm')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('households.inviteRevokeConfirmBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void revoke(invitation)}>
              {t('households.inviteRevokeConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  const atLimit = invitations.filter(isLivePending).length >= MAX_PENDING

  return (
    <TooltipProvider>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-lg font-bold tracking-tight">
          {t('households.invitationsTitle')}
        </h2>
        <Button type="button" onClick={() => void add()} disabled={creating || atLimit}>
          <UserPlusIcon />
          {t('households.addMember')}
        </Button>
      </div>

      {atLimit && (
        <p className="mb-3 text-[13px] font-medium text-muted-foreground">
          {t('households.inviteLimitReached', { max: MAX_PENDING })}
        </p>
      )}
      {error && <p className="mb-3 text-[13px] font-bold text-danger">{error}</p>}

      {invitations.length === 0 ? (
        <p className="text-sm font-medium text-muted-foreground">{t('households.noInvitations')}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {invitations.map((invitation) => (
            <li
              key={invitation.id}
              className="flex items-center justify-between gap-3 rounded-input border border-line bg-card px-3 py-2"
            >
              <div className="flex items-center gap-2.5 text-sm">
                {statusBadge(invitation)}
                {(invitation.status === 'pending' || invitation.status === 'expired') && (
                  <span className="font-medium text-muted-foreground">
                    {invitation.status === 'expired'
                      ? t('households.inviteExpiredAt', {
                          date: formatDateTimeFull(invitation.expires_at),
                        })
                      : t('households.inviteExpiresAt', {
                          date: formatDateTimeFull(invitation.expires_at),
                        })}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-0.5">
                {isLivePending(invitation) ? (
                  <>
                    {copyAction(invitation)}
                    {revokeAction(invitation)}
                  </>
                ) : (
                  deleteAction(invitation)
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </TooltipProvider>
  )
}
