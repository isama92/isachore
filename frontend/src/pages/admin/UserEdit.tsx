import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import { endpoints } from '../../lib/endpoints'
import { routes } from '../../lib/routes'
import { fullName } from '../../lib/user'
import type { ApiTokenStatus, ServerSettings, User } from '../../lib/types'
import { formatDateTime } from '../../lib/format'
import { UserForm } from '@/components/users/UserForm'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'

export default function UserEdit() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user: me } = useAuth()
  const { id = '' } = useParams()

  const [user, setUser] = useState<User | null>(null)
  const [settings, setSettings] = useState<ServerSettings | null>(null)
  // 'failed' rather than null: hiding the panel on a failed read would tell an
  // administrator offboarding an integration that the user holds no token, which is the
  // one wrong answer that looks like a right one.
  const [apiToken, setApiToken] = useState<ApiTokenStatus | 'failed' | null>(null)
  const [apiTokenError, setApiTokenError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    // Only the user fetch drives the not-found state; a settings failure just
    // falls back to defaults so a loadable user can still be edited.
    Promise.all([
      api.get<ServerSettings>(endpoints.adminSettings.root).catch(() => null),
      api.get<User>(endpoints.adminUsers.byId(id)),
      api.get<ApiTokenStatus>(endpoints.adminUsers.apiToken(id)).catch(() => 'failed' as const),
    ])
      .then(([serverSettings, loaded, token]) => {
        if (cancelled) return
        setSettings(serverSettings)
        setUser(loaded)
        setApiToken(token)
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

  async function revokeApiToken() {
    setApiTokenError(null)
    try {
      await api.del(endpoints.adminUsers.apiToken(id))
      setApiToken({ token: null })
      toast.success(t('users.apiTokenRevoked'))
    } catch (err) {
      setApiTokenError(err instanceof ApiError ? err.message : t('users.apiTokenError'))
    }
  }

  async function save(payload: Record<string, unknown>) {
    await api.patch<User>(endpoints.adminUsers.byId(id), payload)
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

      {user && apiToken && (
        <section className="mt-6 rounded-2xl border border-line bg-card p-6">
          <h2 className="mb-2 font-display text-lg font-bold tracking-tight">
            {t('users.apiTokenHeading')}
          </h2>
          {/* Revoking a credential, not disabling a person: the account is untouched.
              There is no way back from here to the token's value, and no admin way to
              mint one - that needs the owner's own password. */}
          <p className="mb-4 text-sm text-muted-foreground">{t('users.apiTokenDescription')}</p>
          {apiToken === 'failed' ? (
            <p className="text-[13px] font-bold text-danger">{t('users.apiTokenLoadError')}</p>
          ) : apiToken.token ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm text-muted-foreground">
                {t('users.apiTokenActiveSince', {
                  date: formatDateTime(apiToken.token.created_at),
                })}
              </p>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:opacity-80"
                  >
                    {t('users.apiTokenRevoke')}
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>{t('users.apiTokenRevokeConfirm')}</AlertDialogTitle>
                    <AlertDialogDescription>
                      {t('users.apiTokenRevokeConfirmBody')}
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                    <AlertDialogAction variant="destructive" onClick={() => void revokeApiToken()}>
                      {t('users.apiTokenRevokeConfirmAction')}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t('users.apiTokenNone')}</p>
          )}
          {apiTokenError && (
            <p className="mt-3 text-[13px] font-bold text-danger">{apiTokenError}</p>
          )}
        </section>
      )}
    </main>
  )
}
