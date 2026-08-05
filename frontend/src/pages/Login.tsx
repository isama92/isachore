import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useSearchParams } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import { ssoErrorKey } from '../lib/sso'
import type { AuthMethods } from '../lib/types'
import BrandCaption from '../components/brand/BrandCaption'
import BrandMark from '../components/brand/BrandMark'
import { Button, buttonVariants } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

// The starting assumption, and therefore also what a failed probe leaves in place: no
// provider, password sign-in available. It is both the overwhelmingly common deployment
// and the safe guess in the one direction that matters - being unable to ask which
// methods exist must never hide the method that always works.
//
// Seeding the state with this rather than null is what keeps the rest of the page free of
// "not loaded yet" special cases: there is no third state to tolerate, so `password_enabled`
// can be read directly and the catch below has nothing to put back.
const PASSWORD_ONLY: AuthMethods = {
  password_enabled: true,
  oidc_enabled: false,
  oidc_provider_name: null,
}

// Label of last resort, matching the backend's own default so an unset OIDC_PROVIDER_NAME
// and a blank one look the same. Not translated, like the brand name and the Catppuccin
// flavours: it stands in for a proper noun the operator was supposed to supply.
const FALLBACK_PROVIDER_NAME = 'SSO'

export default function Login() {
  const { user, loading, login, verifyTwoFactor } = useAuth()
  const { t } = useTranslation()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  // Seeded from ?sso_error=, which is how a refused single sign-on reports itself: the
  // callback is a browser navigation, so the reason arrives in the url rather than in a
  // response body. Held in the same state as a form error so it behaves like one and the
  // next submit clears it, rather than lingering under a fresh attempt.
  const [error, setError] = useState<string | null>(() => {
    const code = searchParams.get('sso_error')
    return code ? t(ssoErrorKey(code)) : null
  })
  const [submitting, setSubmitting] = useState(false)
  // The password step flips this to 'code' when the account has 2FA enabled.
  const [step, setStep] = useState<'password' | 'code'>('password')
  const [code, setCode] = useState('')
  const [recoveryMode, setRecoveryMode] = useState(false)
  const [methods, setMethods] = useState<AuthMethods>(PASSWORD_ONLY)

  // The only request this page makes, and deliberately neither gated on nor gating: a
  // failure is swallowed, leaving the password-only default above in place. There is
  // nothing to report to a visitor here - the form they need is already on screen - and an
  // error state would only be able to take it away.
  const loadMethods = useCallback(
    () =>
      api
        .get<AuthMethods>(endpoints.auth.methods)
        .then((data) => setMethods(data))
        .catch(() => {}),
    [],
  )

  useEffect(() => {
    void loadMethods()
  }, [loadMethods])

  const state = location.state as { from?: string } | null
  const from = state?.from ?? routes.home

  const passwordEnabled = methods.password_enabled
  const ssoEnabled = methods.oidc_enabled
  // The flag alone decides whether the button shows; a missing label falls back rather than
  // hiding it. Hiding was the first attempt and it is worse: under OIDC_ONLY the credential
  // form is gone too, so a blank OIDC_PROVIDER_NAME (a reachable config - the name is
  // cosmetic and deliberately not part of the server's "is it configured" check) would leave
  // a login page with no way in at all. The server now guarantees a non-empty name, so this
  // is the belt to that braces, for a client that cannot know which server version it is
  // talking to.
  const providerName = methods.oidc_provider_name?.trim() || FALLBACK_PROVIDER_NAME
  // A plain navigation to our own backend, which then redirects to the provider. The
  // return target rides in the query string because router state cannot survive a
  // full-page navigation away and back; the backend refuses anything non-relative.
  const ssoHref = `${endpoints.auth.oidcStart}?return_to=${encodeURIComponent(from)}`

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
        {/* The login screen has the room the sidebar header does not, so this is
            where the handwritten caption lives. */}
        <div className="mb-10 flex items-center gap-2.5">
          <BrandMark className="size-11 rounded-xl" />
          <span className="flex flex-col items-start gap-1">
            <BrandCaption className="w-24" />
            <span className="font-display text-[22px] leading-none font-extrabold tracking-tight">
              isachore
            </span>
          </span>
        </div>

        {step === 'password' ? (
          <>
            <h1 className="font-display text-3xl leading-tight font-bold tracking-tight">
              {t('login.welcome')}
            </h1>
            <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted-foreground">
              {t('login.subtitle')}
            </p>

            {passwordEnabled && (
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
                    // Radix swallows Enter on a checkbox (WAI-ARIA says Space is what
                    // toggles one), which is stricter than the native control it stands in
                    // for: Enter inside a real <input type="checkbox"> submits the form.
                    // On a two-field sign-in that is the difference between "Enter works"
                    // and "Enter works unless you tabbed one step too far".
                    //
                    // preventDefault() first, so Radix's own composed handler is skipped -
                    // it runs ours before its own and bails once the default is prevented.
                    // Then requestSubmit(), NOT onSubmit(e): requestSubmit runs the
                    // browser's constraint validation, so Enter here will not post an empty
                    // password any more than Enter in the email field would.
                    //
                    // The two are not otherwise identical, which is what the guard is for.
                    // Implicit submission fires a click at the default button and so does
                    // nothing while that button is disabled; requestSubmit() consults no
                    // button at all. Without `submitting` and `repeat`, holding Enter would
                    // auto-repeat a burst of login attempts straight into the Redis throttle
                    // and lock the user out of their own sign-in.
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter' || e.repeat || submitting) return
                      e.preventDefault()
                      e.currentTarget.form?.requestSubmit()
                    }}
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
            )}

            {/* Deliberately OUTSIDE the form. A second submit-typed control inside it
                would become the default submit button and change what the Enter-key
                handler above does; an anchor is also what this actually is, a plain
                navigation to our own backend, which then redirects to the provider. */}
            {ssoEnabled && (
              <>
                {passwordEnabled && (
                  <div className="my-6 flex items-center gap-3" aria-hidden="true">
                    <span className="h-px flex-1 bg-line" />
                    <span className="text-[12.5px] font-bold tracking-wide text-muted-foreground uppercase">
                      {t('login.or')}
                    </span>
                    <span className="h-px flex-1 bg-line" />
                  </div>
                )}
                <a
                  href={ssoHref}
                  className={cn(
                    buttonVariants({ variant: 'outline', size: 'lg' }),
                    'h-11 w-full text-[15.5px]',
                  )}
                >
                  {t('login.signInWith', { provider: providerName })}
                </a>
              </>
            )}

            {/* The SSO error has nowhere else to go when the credential form is hidden. */}
            {!passwordEnabled && error && (
              <p className="mt-4 text-[13px] font-bold text-danger">{error}</p>
            )}

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
