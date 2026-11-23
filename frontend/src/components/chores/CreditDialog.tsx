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

// "Who gets the credit?" Shown when completing (or, on Home, skipping) a chore that is assigned
// only to other members, so the History and the per-chore stats record the right person.
// Shared by the two list pages; `chore` being non-null is what opens it. `group` picks up the
// calling page's copy, `action` whether it reads "Done as" or "Skip as". Unscheduled chores are
// never due, so they are never skipped and only Home passes `skip`.
export default function CreditDialog({
  group,
  action = 'complete',
  chore,
  onClose,
  onConfirm,
}: {
  group: 'home' | 'unscheduled'
  action?: 'complete' | 'skip'
  chore: { title: string; assignees: HouseholdMember[] } | null
  onClose: () => void
  // Called with the member to credit, or undefined to credit the current user.
  onConfirm: (completedByUserId?: number) => void
}) {
  const { t } = useTranslation()
  // Spelled out rather than built from `action`, so every key stays a checked literal. The skip
  // copy is Home's alone: only Home skips (see above).
  const keys =
    action === 'skip'
      ? ({
          title: 'home.creditSkip.title',
          body: 'home.creditSkip.body',
          as: 'home.creditSkip.skipAs',
          asMe: 'home.creditSkip.skipAsMe',
        } as const)
      : ({
          title: `${group}.credit.title`,
          body: `${group}.credit.body`,
          as: `${group}.credit.doneAs`,
          asMe: `${group}.credit.doneAsMe`,
        } as const)
  return (
    <AlertDialog open={chore !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t(keys.title, { title: chore?.title ?? '' })}</AlertDialogTitle>
          <AlertDialogDescription>
            {t(keys.body, {
              names: chore ? chore.assignees.map(fullName).join(', ') : '',
            })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          {chore?.assignees.map((a) => (
            <AlertDialogAction key={a.id} onClick={() => onConfirm(a.id)}>
              {t(keys.as, { name: fullName(a) })}
            </AlertDialogAction>
          ))}
          <AlertDialogAction onClick={() => onConfirm()}>{t(keys.asMe)}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
