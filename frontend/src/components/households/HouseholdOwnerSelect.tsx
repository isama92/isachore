import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api, ApiError } from '@/lib/api'
import { fullName } from '@/lib/user'
import type { Household, HouseholdMember, Page } from '@/lib/types'
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
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type Props = {
  // Household base URL: PATCHed with { admin_id } to transfer ownership.
  basePath: string
  adminId: number
  // Receives the updated household so the page can reflect the new owner.
  onTransferred: (updated: Household) => void
}

// Lets the owner (or a site admin) hand ownership to another active member.
// Picking a member only stages the choice; a Save button then appears and asks
// for confirmation before the transfer is applied. Renders nothing until there
// is someone other than the current owner to pick.
export function HouseholdOwnerSelect({ basePath, adminId, onTransferred }: Props) {
  const { t } = useTranslation()
  const [members, setMembers] = useState<HouseholdMember[]>([])
  const [pending, setPending] = useState(adminId)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<Page<HouseholdMember>>(`${basePath}/members?page_size=100`)
      .then((data) => {
        if (!cancelled) setMembers(data.items)
      })
      .catch(() => {
        if (!cancelled) setMembers([])
      })
    return () => {
      cancelled = true
    }
  }, [basePath])

  async function confirmTransfer() {
    setError(null)
    try {
      // On success the parent updates the household, so adminId becomes pending
      // and the Save button clears itself.
      const updated = await api.patch<Household>(basePath, { admin_id: pending })
      toast.success(t('households.transferred'))
      onTransferred(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.transferError'))
    }
  }

  // Nothing to transfer to (just the owner, or members not loaded yet).
  if (members.length <= 1) return null

  const dirty = pending !== adminId
  const pendingMember = members.find((m) => m.id === pending)

  return (
    <div
      role="group"
      aria-label={t('households.adminLabel')}
      className="flex max-w-lg flex-col gap-1.5"
    >
      <Label htmlFor="household-admin">{t('households.adminLabel')}</Label>
      <div className="flex items-center gap-2">
        <Select value={String(pending)} onValueChange={(v) => setPending(Number(v))}>
          <SelectTrigger
            id="household-admin"
            className="w-full sm:w-72"
            aria-label={t('households.adminLabel')}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {members.map((m) => (
              <SelectItem key={m.id} value={String(m.id)}>
                {fullName(m)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {dirty && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button type="button" size="lg">
                {t('common.save')}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  {t('households.transferConfirm', {
                    name: pendingMember ? fullName(pendingMember) : '',
                  })}
                </AlertDialogTitle>
                <AlertDialogDescription>
                  {t('households.transferConfirmBody')}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                <AlertDialogAction onClick={() => void confirmTransfer()}>
                  {t('households.transferConfirmAction')}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
      {error && <p className="text-[13px] font-bold text-danger">{error}</p>}
    </div>
  )
}
