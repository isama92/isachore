import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { fullName } from '../lib/user'
import type { InvitationInfo } from '../lib/types'
import { Button } from '@/components/ui/button'

export default function AcceptInvite() {
  const { t } = useTranslation()
  const { user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [loading, setLoading] = useState(true)
  const [info, setInfo] = useState<InvitationInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [joining, setJoining] = useState(false)

  // Only fetch once we know the visitor is logged in — a logged-out visitor is
  // redirected to /login first (below), so we don't hit the endpoint for them.
  // A missing/invalid/expired token 404s into .catch -> the invalid-link state;
  // all setState stays inside the promise callbacks (set-state-in-effect rule).
  useEffect(() => {
    if (!user) return
    let cancelled = false
    api
      .get<InvitationInfo>(`/api/v1/invitations/${token}`)
      .then((data) => {
        if (!cancelled) setInfo(data)
      })
      .catch(() => {
        if (!cancelled) setInfo(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [token, user])

  async function join() {
    setError(null)
    setJoining(true)
    try {
      await api.post(`/api/v1/invitations/${token}/accept`)
      toast.success(t('invite.joined', { household: info?.household_name ?? '' }))
      await navigate('/households')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(t('invite.alreadyMember'))
      } else {
        setError(err instanceof ApiError ? err.message : t('invite.error'))
      }
    } finally {
      setJoining(false)
    }
  }

  // Wait for auth to resolve, then send a logged-out visitor to log in first,
  // carrying the token so login returns them here (Login honours state.from).
  if (authLoading) return null
  if (!user) {
    return <Navigate to="/login" replace state={{ from: `/invite?token=${token}` }} />
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
              {t('invite.invalidTitle')}
            </h1>
            <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted-foreground">
              {t('invite.invalidBody')}
            </p>
            <Link to="/" className="text-[14px] font-bold text-primary hover:text-primary-dark">
              {t('invite.goHome')}
            </Link>
          </>
        ) : (
          <>
            <h1 className="font-display text-3xl leading-tight font-bold tracking-tight">
              {t('invite.title')}
            </h1>
            <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted-foreground">
              {t('invite.invitedBy', {
                household: info.household_name,
                admin: fullName(info.invited_by),
              })}
            </p>

            {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}

            <Button
              type="button"
              size="lg"
              disabled={joining}
              className="h-11 w-full text-[15.5px]"
              onClick={() => void join()}
            >
              {joining ? t('common.saving') : t('invite.join')}
            </Button>
          </>
        )}
      </div>
    </main>
  )
}
