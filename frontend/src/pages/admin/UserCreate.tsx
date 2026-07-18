import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api } from '../../lib/api'
import type { ServerSettings, User } from '../../lib/types'
import { UserForm } from '@/components/users/UserForm'

export default function UserCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [settings, setSettings] = useState<ServerSettings | null>(null)
  const [loading, setLoading] = useState(true)

  // The password field's visibility depends on require_confirmation, so wait for
  // settings before rendering the form (avoids the field flashing in then out).
  useEffect(() => {
    let cancelled = false
    api
      .get<ServerSettings>('/api/v1/settings')
      .then((data) => {
        if (!cancelled) setSettings(data)
      })
      .catch(() => {
        if (!cancelled) setSettings(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function create(payload: Record<string, unknown>) {
    await api.post<User>('/api/v1/users', payload)
    toast.success(t('users.toastCreated'))
    await navigate('/admin/users')
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">{t('users.newUser')}</h1>
      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : (
        <UserForm
          mode="create"
          requireConfirmation={settings?.require_confirmation ?? false}
          smtpConfigured={settings?.smtp_configured ?? false}
          isSelf={false}
          submitLabel={t('users.addUser')}
          cancelTo="/admin/users"
          onSubmit={create}
        />
      )}
    </main>
  )
}
