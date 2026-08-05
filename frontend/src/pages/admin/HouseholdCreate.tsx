import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api } from '../../lib/api'
import { endpoints } from '../../lib/endpoints'
import { routes } from '../../lib/routes'
import type { Household } from '../../lib/types'
import { HouseholdForm, type HouseholdFormValues } from '@/components/households/HouseholdForm'

export default function AdminHouseholdCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  async function create({ name, timezone }: HouseholdFormValues) {
    await api.post<Household>(endpoints.adminHouseholds.root, { name, timezone })
    toast.success(t('households.toastCreated'))
    await navigate(routes.admin.households.list)
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">{t('households.new')}</h1>
      <HouseholdForm
        submitLabel={t('households.add')}
        cancelTo={routes.admin.households.list}
        onSubmit={create}
      />
    </main>
  )
}
