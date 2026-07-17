import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type TokenInfo = { email: string; first_name: string; last_name: string }

export default function ConfirmAccount() {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [loading, setLoading] = useState(true)
  const [info, setInfo] = useState<TokenInfo | null>(null)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // A missing token hits /api/v1/confirm/ which 404s, landing in .catch -> the
  // invalid-link state, same as a bad token. Keeping all setState inside the
  // promise callbacks (never synchronously in the effect) satisfies the
  // set-state-in-effect lint rule.
  const load = useCallback(
    () =>
      api
        .get<TokenInfo>(`/api/v1/confirm/${token}`)
        .then((data) => setInfo(data))
        .catch(() => setInfo(null))
        .finally(() => setLoading(false)),
    [token],
  )

  useEffect(() => {
    void load()
  }, [load])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError(t('confirmAccount.mismatch'))
      return
    }
    if (password.length < 8) {
      setError(t('confirmAccount.tooShort'))
      return
    }
    setSubmitting(true)
    try {
      await api.post(`/api/v1/confirm/${token}`, { password })
      toast.success(t('confirmAccount.success'))
      await refresh()
      await navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('confirmAccount.error'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-7 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-10 flex items-center gap-2.5">
          <div className="grid size-10 place-items-center rounded-xl bg-primary text-[22px] font-extrabold text-primary-foreground shadow-logo">
            ✓
          </div>
          <span className="font-display text-[22px] font-extrabold tracking-tight">isachore</span>
        </div>

        {loading ? (
          <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
        ) : !info ? (
          <>
            <h1 className="font-display text-3xl leading-tight font-bold tracking-tight">
              {t('confirmAccount.invalidTitle')}
            </h1>
            <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted-foreground">
              {t('confirmAccount.invalidBody')}
            </p>
            <Link
              to="/login"
              className="text-[14px] font-bold text-primary hover:text-primary-dark"
            >
              {t('confirmAccount.toLogin')}
            </Link>
          </>
        ) : (
          <>
            <h1 className="font-display text-3xl leading-tight font-bold tracking-tight">
              {t('confirmAccount.title')}
            </h1>
            <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted-foreground">
              {t('confirmAccount.subtitle', { email: info.email })}
            </p>

            <form className="flex flex-col gap-4" onSubmit={(e) => void onSubmit(e)}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">{t('confirmAccount.password')}</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  placeholder={t('common.passwordMin')}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="confirm-password">{t('confirmAccount.confirmPassword')}</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </div>

              {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

              <Button
                type="submit"
                size="lg"
                disabled={submitting}
                className="h-11 w-full text-[15.5px]"
              >
                {submitting ? t('common.saving') : t('confirmAccount.submit')}
              </Button>
            </form>
          </>
        )}
      </div>
    </main>
  )
}
