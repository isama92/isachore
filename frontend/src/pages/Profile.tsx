import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { fullName, initials } from '../lib/user'
import type { User } from '../lib/types'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function Profile() {
  const { user, refresh } = useAuth()

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
      toast.success('Name updated')
      await refresh()
    } catch (err) {
      setNameError(err instanceof ApiError ? err.message : 'Could not update your name')
    } finally {
      setSavingName(false)
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
      toast.success('Photo updated')
      await refresh()
    } catch (err) {
      setAvatarError(err instanceof ApiError ? err.message : 'Could not upload the photo')
    } finally {
      setAvatarBusy(false)
    }
  }

  async function onRemoveAvatar() {
    setAvatarError(null)
    setAvatarBusy(true)
    try {
      await api.del<User>('/api/v1/profile/avatar')
      toast.success('Photo removed')
      await refresh()
    } catch (err) {
      setAvatarError(err instanceof ApiError ? err.message : 'Could not remove the photo')
    } finally {
      setAvatarBusy(false)
    }
  }

  async function onPasswordSubmit(e: FormEvent) {
    e.preventDefault()
    setPasswordError(null)
    if (newPassword !== confirmPassword) {
      setPasswordError('The new passwords do not match')
      return
    }
    if (newPassword.length < 8) {
      setPasswordError('The new password must be at least 8 characters')
      return
    }
    setSavingPassword(true)
    try {
      await api.patch<User>('/api/v1/profile', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      toast.success('Password changed')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      await refresh()
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : 'Could not change your password')
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">Your profile</h1>

      <div className="flex flex-col gap-6">
        {/* Picture */}
        <section className="rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-4 font-display text-lg font-bold tracking-tight">Photo</h2>
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
                  {avatarBusy ? 'Working…' : 'Change photo'}
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
                    Remove
                  </Button>
                )}
              </div>
              <p className="text-xs font-medium text-muted-foreground">
                PNG, JPEG or WebP, up to 5 MB.
              </p>
            </div>
          </div>
          {avatarError && <p className="mt-4 text-[13px] font-bold text-danger">{avatarError}</p>}
        </section>

        {/* Name */}
        <section className="rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-4 font-display text-lg font-bold tracking-tight">Name</h2>
          <form onSubmit={(e) => void onNameSubmit(e)} className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-first-name">First name</Label>
                <Input
                  id="profile-first-name"
                  required
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-last-name">Last name</Label>
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
                {savingName ? 'Saving…' : 'Save name'}
              </Button>
            </div>
          </form>
        </section>

        {/* Password */}
        <section className="rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-4 font-display text-lg font-bold tracking-tight">Password</h2>
          <form onSubmit={(e) => void onPasswordSubmit(e)} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="current-password">Current password</Label>
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
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                placeholder="At least 8 characters"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="confirm-password">Confirm new password</Label>
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
                {savingPassword ? 'Saving…' : 'Change password'}
              </Button>
            </div>
          </form>
        </section>
      </div>
    </main>
  )
}
