import { useTranslation } from 'react-i18next'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { fullName } from '@/lib/user'
import type { HouseholdMember } from '@/lib/types'

// "Who gets the credit?" Shown when completing a chore that is assigned only to other
// members, so the History records the right person. Shared by the two list pages; `chore`
// being non-null is what opens it. `group` picks up the calling page's copy.
export default function CreditDialog({
  group,
  chore,
  onClose,
  onConfirm,
}: {
  group: 'home' | 'unscheduled'
  chore: { title: string; assignees: HouseholdMember[] } | null
  onClose: () => void
  // Called with the member to credit, or undefined to credit the current user.
  onConfirm: (completedByUserId?: number) => void
}) {
  const { t } = useTranslation()
  return (
    <AlertDialog open={chore !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t(`${group}.credit.title`, { title: chore?.title ?? '' })}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t(`${group}.credit.body`, {
              names: chore ? chore.assignees.map(fullName).join(', ') : '',
            })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          {chore?.assignees.map((a) => (
            <AlertDialogAction key={a.id} onClick={() => onConfirm(a.id)}>
              {t(`${group}.credit.doneAs`, { name: fullName(a) })}
            </AlertDialogAction>
          ))}
          <AlertDialogAction onClick={() => onConfirm()}>
            {t(`${group}.credit.doneAsMe`)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
