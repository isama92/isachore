import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Props = {
  initialName?: string
  submitLabel: string
  cancelTo: string
  // Called with the trimmed name. It MUST navigate away on success: the form
  // only clears its saving state on error, so a successful submit is expected to
  // unmount the form (both the create and edit pages navigate back to the list).
  onSubmit: (name: string) => Promise<void>
}

// Shared name form for creating and editing a household (both are dedicated
// pages). The single field is all a household has today.
export function HouseholdForm({ initialName = '', submitLabel, cancelTo, onSubmit }: Props) {
  const { t } = useTranslation()
  const [name, setName] = useState(initialName)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSubmit(name.trim())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.saveError'))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="flex max-w-lg flex-col gap-5">
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
  )
}
