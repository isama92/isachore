import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

// Brand teal; the seed tags use it too. A new tag starts here so the picker is
// never left on an accidental black (#000000).
const DEFAULT_COLOR = '#0d9488'

type Props = {
  initialName?: string
  initialColor?: string
  submitLabel: string
  cancelTo: string
  // Fallback error text (create vs edit differ).
  errorMessage: string
  // Rendered above the fields: the household select on the create page.
  header?: ReactNode
  // Called with the trimmed name and the chosen colour. It MUST navigate away on
  // success: the form only clears its saving state on error, so a successful
  // submit is expected to unmount the form (both pages navigate back to /tags).
  onSubmit: (name: string, color: string) => Promise<void>
}

// Shared name + colour form for creating and editing a tag (both dedicated
// pages), mirroring HouseholdForm/ChoreForm.
export function TagForm({
  initialName = '',
  initialColor = DEFAULT_COLOR,
  submitLabel,
  cancelTo,
  errorMessage,
  header,
  onSubmit,
}: Props) {
  const { t } = useTranslation()
  const [name, setName] = useState(initialName)
  const [color, setColor] = useState(initialColor)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSubmit(name.trim(), color)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : errorMessage)
      setSaving(false)
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="flex w-full max-w-lg flex-col gap-5">
      {header}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="tag-name">{t('tagCreate.nameLabel')}</Label>
        <Input
          id="tag-name"
          required
          maxLength={50}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('tagCreate.namePlaceholder')}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="tag-color">{t('tagCreate.colorLabel')}</Label>
        <div className="flex items-center gap-3">
          <input
            id="tag-color"
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="h-10 w-16 cursor-pointer rounded-input border border-input bg-transparent p-1"
          />
          <span className="font-mono text-sm text-muted-foreground uppercase tabular-nums">
            {color}
          </span>
        </div>
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
