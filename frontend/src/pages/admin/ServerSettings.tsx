import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import { endpoints } from '../../lib/endpoints'
import type { ServerSettings as ServerSettingsData } from '../../lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'

// Mirrors settings.test_email_cooldown on the backend, which enforces the same
// limit server-side (429). This countdown is the UX half: it disables the
// button so a normal user never runs into the 429 in the first place.
const TEST_EMAIL_COOLDOWN_SECONDS = 10

export default function ServerSettings() {
  const { user } = useAuth()
  const { t } = useTranslation()

  // The payload as it came, for everything read-only. One slice rather than one per
  // field: the read-only half of this page is now SMTP plus single sign-on, and eleven
  // useState calls to mirror one object earns nothing.
  const [settings, setSettings] = useState<ServerSettingsData | null>(null)
  // The exception, because it is the one value this page mutates: it needs its own state
  // to be toggled optimistically and rolled back independently of the rest.
  const [requireConfirmation, setRequireConfirmation] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [sendingTest, setSendingTest] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)
  const [testCooldown, setTestCooldown] = useState(0)

  const load = useCallback(
    () =>
      api
        .get<ServerSettingsData>(endpoints.settings.root)
        .then((s) => {
          setSettings(s)
          setRequireConfirmation(s.require_confirmation)
        })
        .catch((err: unknown) => {
          setLoadError(err instanceof ApiError ? err.message : t('serverSettings.loadError'))
        })
        .finally(() => setLoading(false)),
    [t],
  )

  useEffect(() => {
    void load()
  }, [load])

  // Tick the test-email cooldown down to zero, a second at a time. Each tick
  // schedules the next, so the setState only ever fires inside the timer
  // callback, never synchronously in the effect body (the hooks rule).
  useEffect(() => {
    if (testCooldown <= 0) return
    const timer = setTimeout(() => setTestCooldown((s) => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [testCooldown])

  // Optimistic toggle + rollback (mirrors Profile.saveAppearance). Enabling
  // without SMTP configured is rejected by the server (400); the rollback then
  // restores the checkbox and surfaces the reason inline.
  async function toggleConfirmation(next: boolean) {
    const prev = requireConfirmation
    setSaveError(null)
    setSaving(true)
    setRequireConfirmation(next)
    try {
      const s = await api.patch<ServerSettingsData>(endpoints.settings.root, {
        require_confirmation: next,
      })
      setSettings(s)
      setRequireConfirmation(s.require_confirmation)
      toast.success(t('serverSettings.saved'))
    } catch (err) {
      setRequireConfirmation(prev)
      setSaveError(err instanceof ApiError ? err.message : t('serverSettings.saveError'))
    } finally {
      setSaving(false)
    }
  }

  async function sendTestEmail() {
    setTestError(null)
    setSendingTest(true)
    try {
      await api.post(endpoints.settings.testEmail)
      toast.success(t('serverSettings.testEmailSent', { email: user?.email ?? '' }))
    } catch (err) {
      // A 429 means the server-side cooldown caught us (e.g. a second tab); show
      // the translated cooldown note rather than the English backend detail.
      const cooledDown = err instanceof ApiError && err.status === 429
      setTestError(
        cooledDown
          ? t('serverSettings.testEmailCooldownError')
          : err instanceof ApiError
            ? err.message
            : t('serverSettings.testEmailError'),
      )
    } finally {
      // Start the cooldown once the request settles, whatever the outcome: the
      // backend claims its cooldown on any accepted send (success or a relay
      // failure), so mirror that here to keep the button in step.
      setSendingTest(false)
      setTestCooldown(TEST_EMAIL_COOLDOWN_SECONDS)
    }
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {t('serverSettings.title')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : loadError ? (
        <p className="text-[13px] font-bold text-danger">{loadError}</p>
      ) : (
        <div className="flex flex-col gap-6">
          {/* Confirmation toggle (the checkbox label is self-describing, so no
              section heading above it). */}
          <section className="rounded-2xl border border-line bg-card p-6">
            <div className="flex items-start gap-3">
              <Checkbox
                id="require-confirmation"
                className="mt-0.5"
                checked={requireConfirmation}
                disabled={saving}
                onCheckedChange={(v) => void toggleConfirmation(v === true)}
              />
              <div className="flex flex-col gap-1">
                <Label
                  htmlFor="require-confirmation"
                  className="text-sm font-bold tracking-normal text-foreground normal-case"
                >
                  {t('serverSettings.requireConfirmation')}
                </Label>
                <p className="text-[13px] font-medium text-muted-foreground">
                  {t('serverSettings.requireConfirmationHint')}
                </p>
              </div>
            </div>
            {!settings?.smtp_configured && (
              <p className="mt-4 text-[13px] font-medium text-warning">
                {t('serverSettings.smtpNotConfigured')}
              </p>
            )}
            {saveError && <p className="mt-4 text-[13px] font-bold text-danger">{saveError}</p>}
          </section>

          {/* Mail server: read-only address/port from the env + a test-send row. */}
          <section className="rounded-2xl border border-line bg-card p-6">
            <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
              {t('serverSettings.testEmailHeading')}
            </h2>
            <div className="grid grid-cols-[auto_1fr] items-center gap-x-8 gap-y-3 text-sm">
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.serverAddress')}
              </span>
              <span className="font-semibold">
                {settings?.smtp_host ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.serverPort')}
              </span>
              <span className="font-semibold">
                {settings?.smtp_port ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.fromAddress')}
              </span>
              <span className="font-semibold">
                {settings?.smtp_from ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.sendTestEmailLabel')}
              </span>
              <span>
                <Button
                  type="button"
                  size="sm"
                  disabled={!settings?.smtp_configured || sendingTest || testCooldown > 0}
                  onClick={() => void sendTestEmail()}
                >
                  {sendingTest
                    ? t('serverSettings.testEmailSending')
                    : testCooldown > 0
                      ? t('serverSettings.testEmailCooldown', { seconds: testCooldown })
                      : t('serverSettings.testEmail')}
                </Button>
              </span>
            </div>
            {testError && <p className="mt-4 text-[13px] font-bold text-danger">{testError}</p>}
          </section>

          {/* Single sign-on: read-only status, since the whole group is env-driven. The
              redirect URI row is the one an operator needs most - it is derived from
              APP_BASE_URL rather than configured, so it is the value to register with the
              provider and there is nowhere else to read it off. */}
          <section className="rounded-2xl border border-line bg-card p-6">
            <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
              {t('serverSettings.ssoHeading')}
            </h2>
            <div className="grid grid-cols-[auto_1fr] items-center gap-x-8 gap-y-3 text-sm">
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.ssoStatus')}
              </span>
              <span>
                <Badge variant={settings?.oidc_configured ? 'default' : 'outline'}>
                  {settings?.oidc_configured
                    ? t('serverSettings.ssoConfigured')
                    : t('serverSettings.ssoUnconfigured')}
                </Badge>
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.ssoProvider')}
              </span>
              <span className="font-semibold">
                {settings?.oidc_configured
                  ? settings.oidc_provider_name
                  : t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.ssoIssuer')}
              </span>
              <span className="font-semibold break-all">
                {settings?.oidc_issuer ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.ssoClientId')}
              </span>
              <span className="font-semibold break-all">
                {settings?.oidc_client_id ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.ssoRedirectUri')}
              </span>
              <span className="font-semibold break-all">{settings?.oidc_redirect_uri}</span>
            </div>
            {!settings?.oidc_configured && (
              <p className="mt-4 text-[13px] font-medium text-warning">
                {t('serverSettings.ssoNotConfigured')}
              </p>
            )}
            {settings?.oidc_only && (
              <p className="mt-4 text-[13px] font-medium text-warning">
                {t('serverSettings.ssoOnly')}
              </p>
            )}
          </section>
        </div>
      )}
    </main>
  )
}
