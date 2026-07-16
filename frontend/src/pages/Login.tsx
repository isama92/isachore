import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { ApiError } from '../lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function Login() {
  const { user, loading, login } = useAuth()
  const { t } = useTranslation()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const state = location.state as { from?: string } | null
  const from = state?.from ?? '/'

  if (loading) return null
  if (user) return <Navigate to={from} replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('login.error'))
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

        <h1 className="font-display text-3xl leading-tight font-bold tracking-tight">
          {t('login.welcome')}
        </h1>
        <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted-foreground">
          {t('login.subtitle')}
        </p>

        <form className="flex flex-col gap-4" onSubmit={(e) => void onSubmit(e)}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email">{t('common.email')}</Label>
            <Input
              id="email"
              type="email"
              name="email"
              autoComplete="email"
              placeholder={t('login.emailPlaceholder')}
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">{t('common.password')}</Label>
            <Input
              id="password"
              type="password"
              name="password"
              autoComplete="current-password"
              placeholder="••••••••••"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

          <Button
            type="submit"
            size="lg"
            disabled={submitting}
            className="h-11 w-full text-[15.5px]"
          >
            {submitting ? t('login.signingIn') : t('login.signIn')}
          </Button>
        </form>

        <p className="mt-6 text-center text-[13.5px] font-medium text-muted-foreground">
          {t('login.hint')}
        </p>
      </div>
    </main>
  )
}
