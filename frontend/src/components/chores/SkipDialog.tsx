import { useId, useState } from 'react'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { DueChore } from '@/lib/types'

type Mode = 'one' | 'all' | 'custom'

// What one skipped occurrence is called in the copy. Only a plain "every day / week / month /
// year" chore can say "3 days": every 2 days, or a week pinned to Tue and Fri, has occurrences
// that are not one unit apart, so it counts occurrences instead of claiming a span. A week
// pinned to a single day is still one week per occurrence.
function skipUnit(chore: DueChore): 'day' | 'week' | 'month' | 'year' | 'time' {
  if (chore.repeat_interval !== 1 || (chore.weekdays?.length ?? 0) > 1) return 'time'
  switch (chore.repeats) {
    case 'daily':
      return 'day'
    case 'weekly':
      return 'week'
    case 'monthly':
      return 'month'
    case 'yearly':
      return 'year'
    default:
      return 'time'
  }
}

// "Really skip this?", and for a chore with several occurrences due, how many of them.
// `chore` being non-null opens it, like its neighbours on Home. `onConfirm(null)` (no body)
// is only the plain confirm, for a chore with one or none due, which is what it always sent.
// Once the user has picked a number from the list it is always sent as that number, never as
// null, even for "all": the count they saw is the guard against a stale page. If a housemate
// closed the chore meanwhile, or midnight added a slot, the server answers with a 400 or
// leaves a slot due, instead of quietly skipping slots the user never saw.
export default function SkipDialog({
  chore,
  onClose,
  onConfirm,
}: {
  chore: DueChore | null
  onClose: () => void
  onConfirm: (count: number | null) => void
}) {
  return (
    <AlertDialog open={chore !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        {/* Keyed on the chore so the choice resets to the default for every new chore. */}
        {chore && <SkipDialogBody key={chore.id} chore={chore} onConfirm={onConfirm} />}
      </AlertDialogContent>
    </AlertDialog>
  )
}

function SkipDialogBody({
  chore,
  onConfirm,
}: {
  chore: DueChore
  onConfirm: (count: number | null) => void
}) {
  const { t } = useTranslation()
  const inputId = useId()
  const hintId = useId()
  const due = chore.due_count
  // "All until today" by default: a habitual Skip, Skip it does what it always did.
  const [mode, setMode] = useState<Mode>('all')
  const [custom, setCustom] = useState('')

  const title = t('home.skipConfirm', { title: chore.title })

  if (due <= 1) {
    return (
      <>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{t('home.skipConfirmBody')}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction onClick={() => onConfirm(null)}>
            {t('home.skipConfirmAction')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </>
    )
  }

  const unit = skipUnit(chore)
  const units = (count: number) => t(`home.skipMany.units.${unit}`, { count })
  const parsed = Number(custom)
  const customValid =
    custom.trim() !== '' && Number.isInteger(parsed) && parsed >= 1 && parsed <= due
  const count = mode === 'one' ? 1 : mode === 'all' ? due : customValid ? parsed : null

  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        <AlertDialogDescription>
          {t('home.skipMany.body', { due: units(due) })}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <ToggleGroup
        type="single"
        variant="outline"
        aria-label={t('home.skipMany.howMany')}
        // Stacked on a phone: the three labels do not fit side by side in the narrow dialog.
        className="w-full flex-col sm:flex-row"
        value={mode}
        // Radix reports '' when the pressed item is pressed again; a choice is always required.
        onValueChange={(next) => next && setMode(next as Mode)}
      >
        <ToggleGroupItem value="one" className="w-full sm:w-auto sm:flex-auto">
          {t('home.skipMany.one')}
        </ToggleGroupItem>
        <ToggleGroupItem value="all" className="w-full sm:w-auto sm:flex-auto">
          {t('home.skipMany.all', { count: due })}
        </ToggleGroupItem>
        <ToggleGroupItem value="custom" className="w-full sm:w-auto sm:flex-auto">
          {t('home.skipMany.custom')}
        </ToggleGroupItem>
      </ToggleGroup>
      {mode === 'custom' && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={inputId}>{t('home.skipMany.customLabel')}</Label>
          <Input
            id={inputId}
            type="number"
            inputMode="numeric"
            min={1}
            max={due}
            step={1}
            autoFocus
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            aria-invalid={custom !== '' && !customValid}
            aria-describedby={hintId}
          />
          <p id={hintId} className="text-[13px] font-medium text-muted-foreground">
            {t('home.skipMany.customHint', { count: due })}
          </p>
        </div>
      )}
      <AlertDialogFooter>
        <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
        <AlertDialogAction
          disabled={count === null}
          onClick={() => count !== null && onConfirm(count)}
        >
          {count === null
            ? t('home.skipConfirmAction')
            : t('home.skipMany.confirm', { units: units(count) })}
        </AlertDialogAction>
      </AlertDialogFooter>
    </>
  )
}
