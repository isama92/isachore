import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import type { ServerSettings as ServerSettingsData } from '../../lib/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'

export default function ServerSettings() {
  const { user } = useAuth()
  const { t } = useTranslation()

  const [requireConfirmation, setRequireConfirmation] = useState(false)
  const [smtpConfigured, setSmtpConfigured] = useState(false)
  const [smtpHost, setSmtpHost] = useState<string | null>(null)
  const [smtpPort, setSmtpPort] = useState<number | null>(null)
  const [smtpFrom, setSmtpFrom] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [sendingTest, setSendingTest] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)

  const load = useCallback(
    () =>
      api
        .get<ServerSettingsData>('/api/v1/settings')
        .then((s) => {
          setRequireConfirmation(s.require_confirmation)
          setSmtpConfigured(s.smtp_configured)
          setSmtpHost(s.smtp_host)
          setSmtpPort(s.smtp_port)
          setSmtpFrom(s.smtp_from)
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

  // Optimistic toggle + rollback (mirrors Profile.saveAppearance). Enabling
  // without SMTP configured is rejected by the server (400); the rollback then
  // restores the checkbox and surfaces the reason inline.
  async function toggleConfirmation(next: boolean) {
    const prev = requireConfirmation
    setSaveError(null)
    setSaving(true)
    setRequireConfirmation(next)
    try {
      const s = await api.patch<ServerSettingsData>('/api/v1/settings', {
        require_confirmation: next,
      })
      setRequireConfirmation(s.require_confirmation)
      setSmtpConfigured(s.smtp_configured)
      setSmtpHost(s.smtp_host)
      setSmtpPort(s.smtp_port)
      setSmtpFrom(s.smtp_from)
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
      await api.post('/api/v1/settings/test-email')
      toast.success(t('serverSettings.testEmailSent', { email: user?.email ?? '' }))
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : t('serverSettings.testEmailError'))
    } finally {
      setSendingTest(false)
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-5 py-8">
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
            {!smtpConfigured && (
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
                {smtpHost ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.serverPort')}
              </span>
              <span className="font-semibold">
                {smtpPort ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.fromAddress')}
              </span>
              <span className="font-semibold">
                {smtpFrom ?? t('serverSettings.notConfiguredValue')}
              </span>
              <span className="font-medium text-muted-foreground">
                {t('serverSettings.sendTestEmailLabel')}
              </span>
              <span>
                <Button
                  type="button"
                  size="sm"
                  disabled={!smtpConfigured || sendingTest}
                  onClick={() => void sendTestEmail()}
                >
                  {sendingTest
                    ? t('serverSettings.testEmailSending')
                    : t('serverSettings.testEmail')}
                </Button>
              </span>
            </div>
            {testError && <p className="mt-4 text-[13px] font-bold text-danger">{testError}</p>}
          </section>
        </div>
      )}
    </main>
  )
}
