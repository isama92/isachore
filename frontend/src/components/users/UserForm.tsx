import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ApiError } from '@/lib/api'
import type { UserStatus } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export type UserFormInitial = {
  email: string
  first_name: string
  last_name: string
  is_admin: boolean
  status: UserStatus
  confirmed_at: string | null
}

const EMPTY: UserFormInitial = {
  email: '',
  first_name: '',
  last_name: '',
  is_admin: false,
  status: 'active',
  confirmed_at: null,
}

type Props = {
  mode: 'create' | 'edit'
  initial?: UserFormInitial
  // Server settings that shape the form (create hides the password when
  // confirmation is on; edit only offers `waiting_confirmation` with SMTP).
  requireConfirmation: boolean
  smtpConfigured: boolean
  // When editing yourself, you can't change your own admin flag or status.
  isSelf: boolean
  submitLabel: string
  cancelTo: string
  // Called with the API-ready payload. It MUST navigate away on success: the
  // form only clears its saving state on error (mirrors HouseholdForm).
  onSubmit: (payload: Record<string, unknown>) => Promise<void>
}

// Shared create/edit form for admin user management (both are dedicated pages).
export function UserForm({
  mode,
  initial,
  requireConfirmation,
  smtpConfigured,
  isSelf,
  submitLabel,
  cancelTo,
  onSubmit,
}: Props) {
  const { t } = useTranslation()
  const base = initial ?? EMPTY
  const [email, setEmail] = useState(base.email)
  const [firstName, setFirstName] = useState(base.first_name)
  const [lastName, setLastName] = useState(base.last_name)
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(base.is_admin)
  const [status, setStatus] = useState<UserStatus>(base.status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const editing = mode === 'edit'
  // With confirmation on, new users set their own password via an emailed link,
  // so the create form hides the password field.
  const showPasswordField = editing || !requireConfirmation

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const payload: Record<string, unknown> = {
        email,
        first_name: firstName,
        last_name: lastName,
        is_admin: isAdmin,
      }
      if (editing) {
        payload.status = status
        if (password) payload.password = password
      } else if (!requireConfirmation) {
        payload.password = password
      }
      await onSubmit(payload)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('users.saveError'))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="flex w-full max-w-lg flex-col gap-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="user-first-name">{t('common.firstName')}</Label>
          <Input
            id="user-first-name"
            required
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="user-last-name">{t('common.lastName')}</Label>
          <Input
            id="user-last-name"
            required
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="user-email">{t('common.email')}</Label>
          <Input
            id="user-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        {showPasswordField ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-password">{t('common.password')}</Label>
            <Input
              id="user-password"
              type="password"
              required={!editing}
              minLength={8}
              placeholder={editing ? t('users.passwordKeep') : t('common.passwordMin')}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        ) : (
          <p className="self-end pb-2.5 text-[13px] font-medium text-muted-foreground">
            {t('users.passwordViaEmail')}
          </p>
        )}
        <div className="flex items-center gap-2.5 self-end pb-3">
          <Checkbox
            id="is-admin"
            checked={isAdmin}
            disabled={isSelf}
            onCheckedChange={(v) => setIsAdmin(v === true)}
          />
          <Label
            htmlFor="is-admin"
            className="text-sm font-bold tracking-normal text-foreground normal-case"
          >
            {t('users.adminLabel')}
          </Label>
        </div>
      </div>

      {editing && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="user-status">{t('users.statusLabel')}</Label>
          <Select
            value={status}
            disabled={isSelf}
            onValueChange={(v) => setStatus(v as UserStatus)}
          >
            <SelectTrigger id="user-status" className="w-full sm:w-72">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {/* Waiting needs an email to be useful; only offer it when SMTP is
                  configured, or when the user is already in it. */}
              {(smtpConfigured || base.status === 'waiting_confirmation') && (
                <SelectItem value="waiting_confirmation">{t('users.statusWaiting')}</SelectItem>
              )}
              <SelectItem value="active">{t('users.statusActive')}</SelectItem>
              <SelectItem value="disabled">{t('users.statusDisabled')}</SelectItem>
            </SelectContent>
          </Select>
          {requireConfirmation && status === 'active' && !base.confirmed_at && (
            <p className="text-[13px] font-bold text-warning">{t('users.confirmWarning')}</p>
          )}
        </div>
      )}

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
