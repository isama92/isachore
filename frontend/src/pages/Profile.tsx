import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { useTheme } from '../theme/useTheme'
import type { Accent, Flavour } from '../theme/context'
import { ACCENTS, THEMES, supportsAccent } from '../theme/themes'
import i18n from '../i18n/i18n'
import { useLanguage } from '../i18n/useLanguage'
import { LANGUAGES, type Language } from '../i18n/languages'
import { api, ApiError } from '../lib/api'
import { fullName, initials } from '../lib/user'
import type { User } from '../lib/types'
import { cn } from '@/lib/utils'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export default function Profile() {
  const { user, refresh } = useAuth()
  const { t } = useTranslation()
  const { theme, setTheme, accent, setAccent } = useTheme()
  const { language, setLanguage } = useLanguage()

  const [savingAppearance, setSavingAppearance] = useState(false)
  const [appearanceError, setAppearanceError] = useState<string | null>(null)

  const [savingLanguage, setSavingLanguage] = useState(false)
  const [languageError, setLanguageError] = useState<string | null>(null)

  const [firstName, setFirstName] = useState(user?.first_name ?? '')
  const [lastName, setLastName] = useState(user?.last_name ?? '')
  const [savingName, setSavingName] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)

  const fileRef = useRef<HTMLInputElement>(null)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [avatarError, setAvatarError] = useState<string | null>(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)
  const [passwordError, setPasswordError] = useState<string | null>(null)

  if (!user) return null

  async function onNameSubmit(e: FormEvent) {
    e.preventDefault()
    setNameError(null)
    setSavingName(true)
    try {
      await api.patch<User>('/api/v1/profile', { first_name: firstName, last_name: lastName })
      toast.success(t('profile.nameUpdated'))
      await refresh()
    } catch (err) {
      setNameError(err instanceof ApiError ? err.message : t('profile.nameError'))
    } finally {
      setSavingName(false)
    }
  }

  // Theme + accent save as one PATCH. Apply optimistically for an instant
  // preview, then roll back if the server rejects it. Separate handler from the
  // name form so it emits its own {theme, accent_color} request.
  async function saveAppearance(nextTheme: Flavour, nextAccent: Accent) {
    const prevTheme = theme
    const prevAccent = accent
    setAppearanceError(null)
    setSavingAppearance(true)
    setTheme(nextTheme)
    setAccent(nextAccent)
    try {
      await api.patch<User>('/api/v1/profile', { theme: nextTheme, accent_color: nextAccent })
      toast.success(t('profile.appearanceUpdated'))
      await refresh()
    } catch (err) {
      setTheme(prevTheme)
      setAccent(prevAccent)
      setAppearanceError(err instanceof ApiError ? err.message : t('profile.appearanceError'))
    } finally {
      setSavingAppearance(false)
    }
  }

  // Language saves like appearance: apply optimistically for an instant switch,
  // then roll back if the server rejects it. Its own {language} PATCH, separate
  // from theme/accent.
  async function saveLanguage(next: Language) {
    const prev = language
    setLanguageError(null)
    setSavingLanguage(true)
    setLanguage(next)
    try {
      await api.patch<User>('/api/v1/profile', { language: next })
      // Read via the i18n singleton (not the closure's t, which is still the
      // pre-switch language) so the toast confirms in the language just chosen.
      toast.success(i18n.t('profile.languageUpdated'))
      await refresh()
    } catch (err) {
      setLanguage(prev)
      setLanguageError(err instanceof ApiError ? err.message : t('profile.languageError'))
    } finally {
      setSavingLanguage(false)
    }
  }

  async function onPickAvatar(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    // Reset the input so picking the same file again still fires onChange.
    if (fileRef.current) fileRef.current.value = ''
    if (!file) return
    setAvatarError(null)
    setAvatarBusy(true)
    try {
      const data = new FormData()
      data.append('file', file)
      await api.upload<User>('/api/v1/profile/avatar', 'PUT', data)
      toast.success(t('profile.photoUpdated'))
      await refresh()
    } catch (err) {
      setAvatarError(err instanceof ApiError ? err.message : t('profile.photoUploadError'))
    } finally {
      setAvatarBusy(false)
    }
  }

  async function onRemoveAvatar() {
    setAvatarError(null)
    setAvatarBusy(true)
    try {
      await api.del<User>('/api/v1/profile/avatar')
      toast.success(t('profile.photoRemoved'))
      await refresh()
    } catch (err) {
      setAvatarError(err instanceof ApiError ? err.message : t('profile.photoRemoveError'))
    } finally {
      setAvatarBusy(false)
    }
  }

  async function onPasswordSubmit(e: FormEvent) {
    e.preventDefault()
    setPasswordError(null)
    if (newPassword !== confirmPassword) {
      setPasswordError(t('profile.passwordMismatch'))
      return
    }
    if (newPassword.length < 8) {
      setPasswordError(t('profile.passwordTooShort'))
      return
    }
    setSavingPassword(true)
    try {
      await api.patch<User>('/api/v1/profile', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      toast.success(t('profile.passwordChanged'))
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      await refresh()
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : t('profile.passwordError'))
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {t('profile.heading')}
      </h1>

      <div className="flex flex-col gap-6">
        {/* Picture */}
        <section className="rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
            {t('profile.photo')}
          </h2>
          <div className="flex items-center gap-5">
            <Avatar className="size-20">
              {user.avatar_url && <AvatarImage src={user.avatar_url} alt={fullName(user)} />}
              <AvatarFallback className="bg-primary/10 text-xl font-bold text-primary">
                {initials(user)}
              </AvatarFallback>
            </Avatar>
            <div className="flex flex-col gap-2">
              <div className="flex gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => void onPickAvatar(e)}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={avatarBusy}
                  onClick={() => fileRef.current?.click()}
                >
                  {avatarBusy ? t('profile.working') : t('profile.changePhoto')}
                </Button>
                {user.avatar_url && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={avatarBusy}
                    className="text-destructive hover:opacity-80"
                    onClick={() => void onRemoveAvatar()}
                  >
                    {t('profile.remove')}
                  </Button>
                )}
              </div>
              <p className="text-xs font-medium text-muted-foreground">{t('profile.photoHint')}</p>
            </div>
          </div>
          {avatarError && <p className="mt-4 text-[13px] font-bold text-danger">{avatarError}</p>}
        </section>

        {/* Name */}
        <section className="rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
            {t('profile.nameHeading')}
          </h2>
          <form onSubmit={(e) => void onNameSubmit(e)} className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-first-name">{t('common.firstName')}</Label>
                <Input
                  id="profile-first-name"
                  required
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-last-name">{t('common.lastName')}</Label>
                <Input
                  id="profile-last-name"
                  required
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                />
              </div>
            </div>
            {nameError && <p className="text-[13px] font-bold text-danger">{nameError}</p>}
            <div>
              <Button type="submit" size="lg" disabled={savingName}>
                {savingName ? t('common.saving') : t('profile.saveName')}
              </Button>
            </div>
          </form>
        </section>

        {/* Appearance */}
        <section className="rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
            {t('profile.appearance')}
          </h2>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="language-select">{t('profile.language')}</Label>
              <Select
                value={language}
                disabled={savingLanguage}
                onValueChange={(v) => void saveLanguage(v as Language)}
              >
                <SelectTrigger id="language-select" className="w-full sm:w-72">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGES.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {languageError && (
                <p className="text-[13px] font-bold text-danger">{languageError}</p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="theme-select">{t('profile.theme')}</Label>
              <Select
                value={theme}
                disabled={savingAppearance}
                onValueChange={(v) => void saveAppearance(v as Flavour, accent)}
              >
                <SelectTrigger id="theme-select" className="w-full sm:w-72">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>{t('profile.light')}</SelectLabel>
                    {THEMES.filter((th) => th.group === 'light').map((th) => (
                      <SelectItem key={th.id} value={th.id}>
                        {th.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                  <SelectSeparator />
                  <SelectGroup>
                    <SelectLabel>{t('profile.dark')}</SelectLabel>
                    {THEMES.filter((th) => th.group === 'dark').map((th) => (
                      <SelectItem key={th.id} value={th.id}>
                        {th.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>

            {supportsAccent(theme) && (
              <div className="flex flex-col gap-1.5">
                <Label>{t('profile.accentColour')}</Label>
                <div className="flex flex-wrap gap-2">
                  {ACCENTS.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      aria-label={a.label}
                      aria-pressed={accent === a.id}
                      title={a.label}
                      disabled={savingAppearance}
                      onClick={() => void saveAppearance(theme, a.id)}
                      className={cn(
                        'size-7 rounded-full ring-offset-2 ring-offset-card transition disabled:opacity-50',
                        accent === a.id
                          ? 'ring-2 ring-ring'
                          : 'ring-1 ring-border hover:ring-foreground/30',
                      )}
                      style={{ background: `var(--ctp-${a.id})` }}
                    />
                  ))}
                </div>
              </div>
            )}

            {appearanceError && (
              <p className="text-[13px] font-bold text-danger">{appearanceError}</p>
            )}
          </div>
        </section>

        {/* Password */}
        <section className="rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
            {t('profile.passwordHeading')}
          </h2>
          <form onSubmit={(e) => void onPasswordSubmit(e)} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="current-password">{t('profile.currentPassword')}</Label>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                required
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-password">{t('profile.newPassword')}</Label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                placeholder={t('common.passwordMin')}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="confirm-password">{t('profile.confirmPassword')}</Label>
              <Input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            {passwordError && <p className="text-[13px] font-bold text-danger">{passwordError}</p>}
            <div>
              <Button type="submit" size="lg" disabled={savingPassword}>
                {savingPassword ? t('common.saving') : t('profile.changePassword')}
              </Button>
            </div>
          </form>
        </section>
      </div>
    </main>
  )
}
