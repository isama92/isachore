import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import { endpoints } from '../../lib/endpoints'
import { routes } from '../../lib/routes'
import { fullName } from '../../lib/user'
import type { ServerSettings, User } from '../../lib/types'
import { UserForm } from '@/components/users/UserForm'

export default function UserEdit() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user: me } = useAuth()
  const { id = '' } = useParams()

  const [user, setUser] = useState<User | null>(null)
  const [settings, setSettings] = useState<ServerSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    // Only the user fetch drives the not-found state; a settings failure just
    // falls back to defaults so a loadable user can still be edited.
    Promise.all([
      api.get<ServerSettings>(endpoints.settings.root).catch(() => null),
      api.get<User>(endpoints.users.byId(id)),
    ])
      .then(([serverSettings, loaded]) => {
        if (cancelled) return
        setSettings(serverSettings)
        setUser(loaded)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('users.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id, t])

  async function save(payload: Record<string, unknown>) {
    await api.patch<User>(endpoints.users.byId(id), payload)
    toast.success(t('users.toastUpdated'))
    await navigate(routes.admin.users.list)
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {user ? t('users.editTitle', { name: fullName(user) }) : t('users.editHeading')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : !user ? (
        <p className="text-[13px] font-bold text-danger">{error ?? t('users.notFound')}</p>
      ) : (
        <UserForm
          mode="edit"
          initial={user}
          requireConfirmation={settings?.require_confirmation ?? false}
          smtpConfigured={settings?.smtp_configured ?? false}
          isSelf={me?.id === user.id}
          submitLabel={t('common.save')}
          cancelTo={routes.admin.users.list}
          onSubmit={save}
        />
      )}
    </main>
  )
}
