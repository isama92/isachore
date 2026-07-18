import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api } from '../../lib/api'
import type { Household } from '../../lib/types'
import { HouseholdForm } from '@/components/households/HouseholdForm'

export default function AdminHouseholdCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  async function create(name: string) {
    await api.post<Household>('/api/v1/admin/households', { name })
    toast.success(t('households.toastCreated'))
    await navigate('/admin/households')
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">{t('households.new')}</h1>
      <HouseholdForm
        submitLabel={t('households.add')}
        cancelTo="/admin/households"
        onSubmit={create}
      />
    </main>
  )
}
