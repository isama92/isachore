import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import type { RecoveryCodes, TwoFactorSetup } from '../lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

// The plaintext recovery codes, shown once after enabling or regenerating.
function RecoveryCodesView({ codes }: { codes: string[] }) {
  const { t } = useTranslation()
  async function copy() {
    try {
      await navigator.clipboard?.writeText(codes.join('\n'))
      toast.success(t('profile.recoveryCodesCopied'))
    } catch {
      // Clipboard access can be denied; the codes are still visible to copy by hand.
    }
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">{t('profile.recoveryCodesHint')}</p>
      <ul className="grid grid-cols-2 gap-2 rounded-input bg-muted p-3 text-center font-mono text-sm">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => void copy()}
      >
        {t('profile.recoveryCodesCopy')}
      </Button>
    </div>
  )
}

export default function TwoFactorSettings() {
  const { user, refresh } = useAuth()
  const { t } = useTranslation()
  const enabled = user?.two_factor_enabled ?? false

  // Enable wizard: 'scan' shows the QR + confirm-code field, 'recovery' shows
  // the backup codes handed back on success.
  const [enableOpen, setEnableOpen] = useState(false)
  const [enablePhase, setEnablePhase] = useState<'scan' | 'recovery'>('scan')
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null)
  const [confirmCode, setConfirmCode] = useState('')
  const [enableBusy, setEnableBusy] = useState(false)
  const [enableError, setEnableError] = useState<string | null>(null)
  const [codes, setCodes] = useState<string[]>([])

  // Disable / regenerate both prompt for a current code; regenerate then shows
  // a fresh batch (reusing the codes state + RecoveryCodesView).
  const [disableOpen, setDisableOpen] = useState(false)
  const [regenOpen, setRegenOpen] = useState(false)
  const [promptCode, setPromptCode] = useState('')
  const [promptBusy, setPromptBusy] = useState(false)
  const [promptError, setPromptError] = useState<string | null>(null)
  const [regenPhase, setRegenPhase] = useState<'prompt' | 'recovery'>('prompt')

  async function openEnable() {
    setEnablePhase('scan')
    setConfirmCode('')
    setCodes([])
    setSetup(null)
    setEnableError(null)
    setEnableBusy(true)
    setEnableOpen(true)
    try {
      setSetup(await api.post<TwoFactorSetup>(endpoints.profile.twoFactor.setup))
    } catch (err) {
      setEnableError(err instanceof ApiError ? err.message : t('profile.twoFactorError'))
    } finally {
      setEnableBusy(false)
    }
  }

  async function onConfirmEnable(e: FormEvent) {
    e.preventDefault()
    setEnableError(null)
    setEnableBusy(true)
    try {
      const res = await api.post<RecoveryCodes>(endpoints.profile.twoFactor.confirm, {
        code: confirmCode.trim(),
      })
      setCodes(res.recovery_codes)
      setEnablePhase('recovery')
      toast.success(t('profile.twoFactorEnabledToast'))
      await refresh()
    } catch (err) {
      setEnableError(err instanceof ApiError ? err.message : t('profile.twoFactorError'))
    } finally {
      setEnableBusy(false)
    }
  }

  function openDisable() {
    setPromptCode('')
    setPromptError(null)
    setDisableOpen(true)
  }

  async function onDisable(e: FormEvent) {
    e.preventDefault()
    setPromptError(null)
    setPromptBusy(true)
    try {
      await api.post(endpoints.profile.twoFactor.disable, { code: promptCode.trim() })
      toast.success(t('profile.twoFactorDisabledToast'))
      setDisableOpen(false)
      await refresh()
    } catch (err) {
      setPromptError(err instanceof ApiError ? err.message : t('profile.twoFactorError'))
    } finally {
      setPromptBusy(false)
    }
  }

  function openRegen() {
    setPromptCode('')
    setCodes([])
    setPromptError(null)
    setRegenPhase('prompt')
    setRegenOpen(true)
  }

  async function onRegen(e: FormEvent) {
    e.preventDefault()
    setPromptError(null)
    setPromptBusy(true)
    try {
      const res = await api.post<RecoveryCodes>(endpoints.profile.twoFactor.recoveryCodes, {
        code: promptCode.trim(),
      })
      setCodes(res.recovery_codes)
      setRegenPhase('recovery')
      toast.success(t('profile.recoveryCodesRegeneratedToast'))
    } catch (err) {
      setPromptError(err instanceof ApiError ? err.message : t('profile.twoFactorError'))
    } finally {
      setPromptBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={enabled ? 'default' : 'outline'}>
          {enabled ? t('profile.twoFactorEnabled') : t('profile.twoFactorDisabled')}
        </Badge>
        <p className="text-sm text-muted-foreground">{t('profile.twoFactorDescription')}</p>
      </div>

      {enabled ? (
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" onClick={openRegen}>
            {t('profile.twoFactorRegenerate')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive hover:opacity-80"
            onClick={openDisable}
          >
            {t('profile.twoFactorDisable')}
          </Button>
        </div>
      ) : (
        <div>
          <Button type="button" size="lg" onClick={() => void openEnable()}>
            {t('profile.twoFactorEnable')}
          </Button>
        </div>
      )}

      {/* Enable wizard */}
      <Dialog open={enableOpen} onOpenChange={setEnableOpen}>
        <DialogContent>
          {enablePhase === 'scan' ? (
            <>
              <DialogHeader>
                <DialogTitle>{t('profile.twoFactorSetupTitle')}</DialogTitle>
                <DialogDescription>{t('profile.twoFactorSetupStep')}</DialogDescription>
              </DialogHeader>
              {setup ? (
                <form onSubmit={(e) => void onConfirmEnable(e)} className="flex flex-col gap-4">
                  <img
                    src={setup.qr}
                    alt={t('profile.twoFactorQrAlt')}
                    className="mx-auto size-44 rounded-input bg-white p-2"
                  />
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="totp-manual-key">{t('profile.twoFactorManualKey')}</Label>
                    <Input
                      id="totp-manual-key"
                      readOnly
                      value={setup.secret}
                      className="font-mono"
                      onFocus={(e) => e.currentTarget.select()}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="totp-confirm">{t('profile.twoFactorCodeLabel')}</Label>
                    <Input
                      id="totp-confirm"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      placeholder={t('profile.twoFactorCodePlaceholder')}
                      required
                      value={confirmCode}
                      onChange={(e) => setConfirmCode(e.target.value)}
                    />
                  </div>
                  {enableError && (
                    <p className="text-[13px] font-bold text-danger">{enableError}</p>
                  )}
                  <Button type="submit" size="lg" disabled={enableBusy}>
                    {enableBusy ? t('common.saving') : t('profile.twoFactorConfirm')}
                  </Button>
                </form>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {enableError ?? t('common.loading')}
                </p>
              )}
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>{t('profile.recoveryCodesTitle')}</DialogTitle>
              </DialogHeader>
              <RecoveryCodesView codes={codes} />
              <Button type="button" size="lg" onClick={() => setEnableOpen(false)}>
                {t('profile.recoveryCodesDone')}
              </Button>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Disable */}
      <Dialog open={disableOpen} onOpenChange={setDisableOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('profile.twoFactorDisableTitle')}</DialogTitle>
            <DialogDescription>{t('profile.twoFactorDisableHint')}</DialogDescription>
          </DialogHeader>
          <form onSubmit={(e) => void onDisable(e)} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="totp-disable">{t('profile.twoFactorCodeLabel')}</Label>
              <Input
                id="totp-disable"
                autoComplete="one-time-code"
                required
                value={promptCode}
                onChange={(e) => setPromptCode(e.target.value)}
              />
            </div>
            {promptError && <p className="text-[13px] font-bold text-danger">{promptError}</p>}
            <Button type="submit" size="lg" variant="destructive" disabled={promptBusy}>
              {promptBusy ? t('common.saving') : t('profile.twoFactorDisable')}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* Regenerate recovery codes */}
      <Dialog open={regenOpen} onOpenChange={setRegenOpen}>
        <DialogContent>
          {regenPhase === 'prompt' ? (
            <>
              <DialogHeader>
                <DialogTitle>{t('profile.twoFactorRegenerate')}</DialogTitle>
                <DialogDescription>{t('profile.twoFactorRegenerateHint')}</DialogDescription>
              </DialogHeader>
              <form onSubmit={(e) => void onRegen(e)} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="totp-regen">{t('profile.twoFactorCodeLabel')}</Label>
                  <Input
                    id="totp-regen"
                    autoComplete="one-time-code"
                    required
                    value={promptCode}
                    onChange={(e) => setPromptCode(e.target.value)}
                  />
                </div>
                {promptError && <p className="text-[13px] font-bold text-danger">{promptError}</p>}
                <Button type="submit" size="lg" disabled={promptBusy}>
                  {promptBusy ? t('common.saving') : t('profile.twoFactorConfirm')}
                </Button>
              </form>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>{t('profile.recoveryCodesTitle')}</DialogTitle>
              </DialogHeader>
              <RecoveryCodesView codes={codes} />
              <Button type="button" size="lg" onClick={() => setRegenOpen(false)}>
                {t('profile.recoveryCodesDone')}
              </Button>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
