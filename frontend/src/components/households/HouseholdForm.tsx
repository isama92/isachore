import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ApiError } from '@/lib/api'
import { browserTimezone } from '@/lib/timezones'
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
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TimezoneSelect } from './TimezoneSelect'

export type HouseholdFormValues = {
  name: string
  timezone: string
}

type Props = {
  initialName?: string
  // Absent on the create pages, where the browser's own zone is the sensible starting guess.
  // The edit pages pass the stored one.
  initialTimezone?: string
  submitLabel: string
  cancelTo: string
  // Called with the trimmed name and the chosen zone. It MUST navigate away on success: the
  // form only clears its saving state on error, so a successful submit is expected to
  // unmount the form (both the create and edit pages navigate back to the list).
  onSubmit: (values: HouseholdFormValues) => Promise<void>
}

// Shared form for creating and editing a household (both are dedicated pages): its name and
// the timezone its chores are due in.
//
// Changing the zone re-dates every scheduled chore in the household (the backend re-anchors
// the open occurrences so they keep their local dates), so that one goes through a
// confirmation. The dialog is *controlled* and rendered once rather than wrapped around an
// AlertDialogTrigger, for the same reason the member-role dialog is: the thing that opens it
// is a form submit, not a button click, so there is nothing for a trigger to wrap.
export function HouseholdForm({
  initialName = '',
  initialTimezone,
  submitLabel,
  cancelTo,
  onSubmit,
}: Props) {
  const { t } = useTranslation()
  const [name, setName] = useState(initialName)
  // Lazily initialised: `browserTimezone()` reads Intl and builds the zone list, and this
  // would otherwise run on every render.
  const [timezone, setTimezone] = useState(() => initialTimezone ?? browserTimezone())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  // Only an *edit* that moves the zone needs confirming. On create there is nothing to
  // re-date, and `initialTimezone` being undefined is exactly what says so.
  const timezoneMoved = initialTimezone !== undefined && timezone !== initialTimezone

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await onSubmit({ name: name.trim(), timezone })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.saveError'))
      setSaving(false)
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (timezoneMoved) {
      setConfirming(true)
      return
    }
    void save()
  }

  return (
    <>
      <form onSubmit={handleSubmit} className="flex w-full max-w-lg flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="household-name">{t('households.nameLabel')}</Label>
          <Input
            id="household-name"
            required
            maxLength={255}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('households.namePlaceholder')}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label id="household-timezone-label" htmlFor="household-timezone">
            {t('households.timezoneLabel')}
          </Label>
          <TimezoneSelect
            id="household-timezone"
            labelledBy="household-timezone-label"
            value={timezone}
            onChange={setTimezone}
          />
          <p className="text-[13px] text-muted-foreground">{t('households.timezoneHint')}</p>
        </div>
        {error && <p className="text-[13px] font-bold text-danger">{error}</p>}
        <div className="flex gap-2">
          <Button type="submit" size="lg" disabled={saving}>
            {saving ? t('common.saving') : submitLabel}
          </Button>
          <Button asChild type="button" variant="ghost" size="lg">
            <Link to={cancelTo}>{t('common.cancel')}</Link>
          </Button>
        </div>
      </form>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('households.timezoneConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('households.timezoneConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            {/* Cancelling needs no revert: the Select is controlled by `timezone`, which the
                dialog never touched. The form simply stays as the user left it. */}
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void save()}>
              {t('households.timezoneConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
