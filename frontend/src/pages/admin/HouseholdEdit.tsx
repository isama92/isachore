import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { ArchiveRestoreIcon } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { endpoints } from '../../lib/endpoints'
import { routes } from '../../lib/routes'
import type { Household } from '../../lib/types'
import { HouseholdForm } from '@/components/households/HouseholdForm'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export default function AdminHouseholdEdit() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { id = '' } = useParams()

  const [household, setHousehold] = useState<Household | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<Household>(endpoints.adminHouseholds.byId(id))
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
    await api.patch<Household>(endpoints.adminHouseholds.byId(id), { name })
    toast.success(t('households.toastUpdated'))
    await navigate(routes.admin.households.list)
  }

  async function restore() {
    setError(null)
    try {
      const updated = await api.post<Household>(endpoints.adminHouseholds.restore(id))
      toast.success(t('households.restored'))
      setHousehold(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('households.restoreError'))
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {t('households.edit')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : !household ? (
        <p className="text-[13px] font-bold text-danger">{error ?? t('households.notFound')}</p>
      ) : (
        <>
          {household.deleted_at && (
            <div className="mb-6 flex items-center gap-3">
              <Badge variant="destructive">{t('households.statusDeleted')}</Badge>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button type="button" variant="outline" size="sm">
                    <ArchiveRestoreIcon />
                    {t('households.restore')}
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      {t('households.restoreConfirm', { name: household.name })}
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      {t('households.restoreConfirmBody')}
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                    <AlertDialogAction onClick={() => void restore()}>
                      {t('households.restoreConfirmAction')}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          )}
          {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}
          <HouseholdForm
            initialName={household.name}
            submitLabel={t('common.save')}
            cancelTo={routes.admin.households.list}
            onSubmit={save}
          />
          <div className="mt-6">
            <HouseholdOwnerSelect
              basePath={endpoints.adminHouseholds.byId(household.id)}
              adminId={household.admin_id}
              onTransferred={setHousehold}
            />
          </div>
          <section className="mt-10">
            <h2 className="mb-4 font-display text-lg font-bold tracking-tight">
              {t('households.membersTitle')}
            </h2>
            {/* `viewerUnrestricted`: a site admin may set any of the three roles here, the same
                reach as the household's own owner. The organiser asymmetry on the user surface
                is a rule about a household member, not about an operator. */}
            <HouseholdMembersTable
              basePath={endpoints.adminHouseholds.byId(household.id)}
              adminId={household.admin_id}
              canManage
              viewerUnrestricted
            />
          </section>
        </>
      )}
    </main>
  )
}
