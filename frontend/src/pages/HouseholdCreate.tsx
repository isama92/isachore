import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { api } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import type { Household } from '../lib/types'
import { HouseholdForm, type HouseholdFormValues } from '@/components/households/HouseholdForm'

export default function HouseholdCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { refresh } = useAuth()

  async function create({ name, timezone }: HouseholdFormValues) {
    await api.post<Household>(endpoints.households.root, { name, timezone })
    // Creating a household makes you its organiser, so the caller's roles just changed and
    // the sidebar reads them from the auth context. Without this refresh a brand-new account
    // - the state every install and every new user starts in, and the reason this page is the
    // documented first step - would create their household and still see the no-household nav,
    // with the management pages bouncing off RequireRole until they reloaded by hand.
    await refresh()
    toast.success(t('households.toastCreated'))
    await navigate(routes.households.list)
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">{t('households.new')}</h1>
      <HouseholdForm
        submitLabel={t('households.add')}
        cancelTo={routes.households.list}
        onSubmit={create}
      />
    </main>
  )
}
