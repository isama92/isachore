import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { copyToClipboard } from '../lib/clipboard'
import { endpoints } from '../lib/endpoints'
import { formatDateTime } from '../lib/format'
import type { ApiTokenCreated, ApiTokenStatus } from '../lib/types'
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

// The plaintext token, shown once after generating it. Same shape as
// RecoveryCodesView in TwoFactorSettings.tsx, so the app has one way of handing
// over a secret it will never show again.
function GeneratedToken({ token }: { token: string }) {
  const { t } = useTranslation()
  const [copyError, setCopyError] = useState<string | null>(null)
  async function copy() {
    // Reported rather than swallowed. This token is on screen once, so "it looks like it
    // copied" is the one outcome that costs the user something they cannot get back.
    if (await copyToClipboard(token)) {
      setCopyError(null)
      toast.success(t('profile.apiTokenCopied'))
    } else {
      setCopyError(t('profile.apiTokenCopyError'))
    }
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">{t('profile.apiTokenRevealHint')}</p>
      <Input
        readOnly
        aria-label={t('profile.apiTokenValueLabel')}
        value={token}
        className="font-mono"
        onFocus={(e) => e.currentTarget.select()}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => void copy()}
      >
        {t('profile.apiTokenCopy')}
      </Button>
      {copyError && <p className="text-[13px] font-bold text-danger">{copyError}</p>}
    </div>
  )
}

export default function ApiTokenSettings() {
  const { t } = useTranslation()

  const [status, setStatus] = useState<ApiTokenStatus | null>(null)
  // Two pieces, so the effect below needs no `t` and can depend on nothing: the server's
  // sentence when it gave one, and a flag for "the read failed" that renders a translated
  // fallback at render time instead. With `t` in the deps the status was refetched every
  // time the user switched language, which this same page hosts the control for.
  const [loadFailed, setLoadFailed] = useState(false)
  const [loadDetail, setLoadDetail] = useState<string | null>(null)

  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The generated token lives in component state and nowhere else. Closing the
  // dialog drops it, which is the whole point of showing it once.
  const [revealed, setRevealed] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<ApiTokenStatus>(endpoints.profile.apiToken)
      .then((loaded) => {
        if (!cancelled) setStatus(loaded)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadFailed(true)
        setLoadDetail(err instanceof ApiError ? err.message : null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function onGenerate(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const created = await api.post<ApiTokenCreated>(endpoints.profile.apiToken, {
        current_password: password,
      })
      setStatus({ token: { created_at: created.created_at } })
      setRevealed(created.token)
      setPassword('')
      toast.success(t('profile.apiTokenCreated'))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('profile.apiError'))
      // Re-read, because the refusal may mean this panel is out of date rather than that
      // the request was wrong: a token minted in another tab answers 409, and without this
      // the form goes on offering Generate for an account that already has one, failing
      // identically until the page is reloaded. A wrong password is not that case.
      if (!(err instanceof ApiError) || err.status !== 400) {
        setStatus(await api.get<ApiTokenStatus>(endpoints.profile.apiToken).catch(() => status))
      }
    } finally {
      setBusy(false)
    }
  }

  async function onDelete() {
    setError(null)
    try {
      await api.del(endpoints.profile.apiToken)
      setStatus({ token: null })
      toast.success(t('profile.apiTokenDeleted'))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('profile.apiError'))
    }
  }

  if (status === null) {
    return loadFailed ? (
      <p className="text-[13px] font-bold text-danger">{loadDetail ?? t('profile.apiError')}</p>
    ) : (
      <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
    )
  }

  const existing = status.token

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={existing ? 'default' : 'outline'}>
          {existing ? t('profile.apiTokenActive') : t('profile.apiTokenNone')}
        </Badge>
        <p className="text-sm text-muted-foreground">{t('profile.apiDescription')}</p>
      </div>

      {/* Says what the token does NOT reach. Without it, somebody wiring up a client
          would reasonably read the 403 on an admin or profile route as a bug rather
          than as the boundary it is. */}
      <p className="text-[13px] text-muted-foreground">{t('profile.apiTokenScope')}</p>

      {existing ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-muted-foreground">
            {t('profile.apiTokenCreatedOn', { date: formatDateTime(existing.created_at) })}
          </p>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive hover:opacity-80"
              >
                {t('profile.apiTokenDelete')}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t('profile.apiTokenDeleteConfirm')}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t('profile.apiTokenDeleteConfirmBody')}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                <AlertDialogAction variant="destructive" onClick={() => void onDelete()}>
                  {t('profile.apiTokenDeleteConfirmAction')}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      ) : (
        <form onSubmit={(e) => void onGenerate(e)} className="flex flex-col gap-4">
          <div className="flex max-w-sm flex-col gap-1.5">
            <Label htmlFor="api-token-password">{t('profile.currentPassword')}</Label>
            <Input
              id="api-token-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="text-[13px] text-muted-foreground">{t('profile.apiTokenPasswordHint')}</p>
          </div>
          <div>
            <Button type="submit" size="lg" disabled={busy}>
              {busy ? t('common.saving') : t('profile.apiTokenGenerate')}
            </Button>
          </div>
        </form>
      )}

      {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

      <Dialog
        open={revealed !== null}
        onOpenChange={(open) => {
          if (!open) setRevealed(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('profile.apiTokenRevealTitle')}</DialogTitle>
            <DialogDescription>{t('profile.apiTokenRevealSubtitle')}</DialogDescription>
          </DialogHeader>
          {revealed && <GeneratedToken token={revealed} />}
          <Button type="button" size="lg" onClick={() => setRevealed(null)}>
            {t('profile.apiTokenRevealDone')}
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  )
}
