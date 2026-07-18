import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { LogOutIcon } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import type { Household } from '../lib/types'
import { HouseholdForm } from '@/components/households/HouseholdForm'
import { HouseholdInvitations } from '@/components/households/HouseholdInvitations'
import { HouseholdMembersTable } from '@/components/households/HouseholdMembersTable'
import { HouseholdOwnerSelect } from '@/components/households/HouseholdOwnerSelect'
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
import { Label } from '@/components/ui/label'

export default function HouseholdEdit() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user: me } = useAuth()
  const { id = '' } = useParams()

  const [household, setHousehold] = useState<Household | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<Household>(endpoints.households.byId(id))
      .then((data) => {
        if (!cancelled) setHousehold(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('households.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id, t])

  async function save(name: string) {
    await api.patch<Household>(endpoints.households.byId(id), { name })
    toast.success(t('households.toastUpdated'))
    await navigate(routes.households.list)
  }

  async function leave() {
    setError(null)
    try {
      await api.post(endpoints.households.leave(id))
      toast.success(t('households.left'))
      await navigate(routes.households.list)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.leaveError'))
    }
  }

  // Only the owner may edit; other members see a read-only view.
  const canManage = !!household && me?.id === household.admin_id
  const basePath = endpoints.households.byId(id)

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {household && !canManage ? household.name : t('households.edit')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : !household ? (
        <p className="text-[13px] font-bold text-danger">{error ?? t('households.notFound')}</p>
      ) : canManage ? (
        <>
          <HouseholdForm
            initialName={household.name}
            submitLabel={t('common.save')}
            cancelTo={routes.households.list}
            onSubmit={save}
          />
          <div className="mt-6">
            <HouseholdOwnerSelect
              basePath={basePath}
              adminId={household.admin_id}
              onTransferred={setHousehold}
            />
          </div>
          <section className="mt-10">
            <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
              {t('households.membersTitle')}
            </h2>
            <HouseholdMembersTable basePath={basePath} adminId={household.admin_id} canManage />
          </section>
          <section className="mt-10">
            <HouseholdInvitations basePath={basePath} />
          </section>
        </>
      ) : (
        <>
          <div className="flex max-w-lg flex-col gap-1.5">
            <Label>{t('households.nameLabel')}</Label>
            <p className="font-semibold">{household.name}</p>
          </div>
          <div className="mt-6">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  className="text-destructive hover:text-destructive"
                >
                  <LogOutIcon />
                  {t('households.leave')}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>
                    {t('households.leaveConfirm', { name: household.name })}
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    {t('households.leaveConfirmBody')}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                  <AlertDialogAction variant="destructive" onClick={() => void leave()}>
                    {t('households.leaveConfirmAction')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
          {error && <p className="mt-4 text-[13px] font-bold text-danger">{error}</p>}
          <section className="mt-10">
            <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
              {t('households.membersTitle')}
            </h2>
            <HouseholdMembersTable
              basePath={basePath}
              adminId={household.admin_id}
              canManage={false}
            />
          </section>
        </>
      )}
    </main>
  )
}
