import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { ApiError } from '../lib/api'
import { routes } from '../lib/routes'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function Login() {
  const { user, loading, login, verifyTwoFactor } = useAuth()
  const { t } = useTranslation()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // The password step flips this to 'code' when the account has 2FA enabled.
  const [step, setStep] = useState<'password' | 'code'>('password')
  const [code, setCode] = useState('')
  const [recoveryMode, setRecoveryMode] = useState(false)

  const state = location.state as { from?: string } | null
  const from = state?.from ?? routes.home

  if (loading) return null
  if (user) return <Navigate to={from} replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const result = await login(email, password, remember)
      if (result?.twoFactorRequired) setStep('code')
      // Otherwise the user is signed in and the redirect above takes over.
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('login.error'))
    } finally {
      setSubmitting(false)
    }
  }

  async function onVerify(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await verifyTwoFactor(code.trim())
      // On success the user is set and the redirect above takes over.
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('login.twoFactorError'))
    } finally {
      setSubmitting(false)
    }
  }

  function backToPassword() {
    setStep('password')
    setCode('')
    setRecoveryMode(false)
    setError(null)
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

        {step === 'password' ? (
          <>
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

              <div className="flex items-center gap-2.5">
                <Checkbox
                  id="remember"
                  checked={remember}
                  onCheckedChange={(v) => setRemember(v === true)}
                />
                <Label
                  htmlFor="remember"
                  className="text-sm font-bold tracking-normal text-foreground normal-case"
                >
                  {t('login.rememberMe')}
                </Label>
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
          </>
        ) : (
          <>
            <h1 className="font-display text-3xl leading-tight font-bold tracking-tight">
              {t('login.twoFactorTitle')}
            </h1>
            <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted-foreground">
              {recoveryMode ? t('login.twoFactorRecoverySubtitle') : t('login.twoFactorSubtitle')}
            </p>

            <form className="flex flex-col gap-4" onSubmit={(e) => void onVerify(e)}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="code">
                  {recoveryMode ? t('login.recoveryCode') : t('login.code')}
                </Label>
                <Input
                  id="code"
                  name="code"
                  // A TOTP is numeric; a recovery code is alphanumeric.
                  inputMode={recoveryMode ? 'text' : 'numeric'}
                  autoComplete="one-time-code"
                  autoFocus
                  placeholder={
                    recoveryMode ? t('login.recoveryCodePlaceholder') : t('login.codePlaceholder')
                  }
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </div>

              {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

              <Button
                type="submit"
                size="lg"
                disabled={submitting}
                className="h-11 w-full text-[15.5px]"
              >
                {submitting ? t('login.verifying') : t('login.verify')}
              </Button>
            </form>

            <div className="mt-6 flex flex-col items-center gap-2 text-[13.5px] font-medium">
              <button
                type="button"
                className="text-primary hover:underline"
                onClick={() => {
                  setRecoveryMode((v) => !v)
                  // The two formats differ (numeric TOTP vs alphanumeric code),
                  // so drop whatever was half-typed for the other one.
                  setCode('')
                  setError(null)
                }}
              >
                {recoveryMode ? t('login.useAuthenticator') : t('login.useRecoveryCode')}
              </button>
              <button
                type="button"
                className="text-muted-foreground hover:underline"
                onClick={backToPassword}
              >
                {t('login.backToSignIn')}
              </button>
            </div>
          </>
        )}
      </div>
    </main>
  )
}
