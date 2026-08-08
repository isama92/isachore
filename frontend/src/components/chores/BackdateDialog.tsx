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
import { formatDateTime } from '@/lib/format'
import type { DueChore } from '@/lib/types'

// "When did you do it?" Shown before completing an overdue chore, so the one somebody did
// and forgot to tick can be recorded against its own due day instead of now. That reads as
// on time AND advances the chore one slot rather than jumping past every occurrence it
// missed, so a backlog is offered one day at a time.
//
// Action buttons rather than a radio group and a confirm: this chains straight into
// CreditDialog for a chore assigned to somebody else, and two dialogs deep is no place to
// spend an extra tap. `chore` being non-null is what opens it, the same shape as its
// neighbours. No `group` prop either - Home is the only caller, since an unscheduled chore is
// never due and so never overdue.
export default function BackdateDialog({
  chore,
  onClose,
  onConfirm,
}: {
  chore: DueChore | null
  onClose: () => void
  // true records the completion against the chore's due day, false against now.
  onConfirm: (backdate: boolean) => void
}) {
  const { t } = useTranslation()
  // The household's zone, not the viewer's: the slot is stored as local midnight there, so
  // any other zone prints the adjacent day and contradicts the "2 days overdue" on the row
  // that opened this.
  const dueDate = chore ? formatDateTime(chore.next_due, chore.household.timezone) : ''
  return (
    <AlertDialog open={chore !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t('home.backdate.title', { title: chore?.title ?? '' })}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t('home.backdate.body', { date: dueDate })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction onClick={() => onConfirm(false)}>
            {t('home.backdate.justNow')}
          </AlertDialogAction>
          <AlertDialogAction onClick={() => onConfirm(true)}>
            {t('home.backdate.onDate', { date: dueDate })}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
