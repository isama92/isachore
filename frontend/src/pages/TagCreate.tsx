import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import { TagForm } from '@/components/tags/TagForm'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Household, Page, Tag } from '../lib/types'

export default function TagCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [households, setHouseholds] = useState<Household[]>([])
  const [householdId, setHouseholdId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Load the user's households once; default the tag to the lowest-id one.
  useEffect(() => {
    let cancelled = false
    api
      .get<Page<Household>>(`${endpoints.households.root}?sort_by=id&sort_dir=asc&page_size=100`)
      .then((page) => {
        if (cancelled) return
        setHouseholds(page.items)
        setHouseholdId(page.items[0]?.id ?? null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('tagCreate.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  async function handleSubmit(name: string, color: string) {
    await api.post<Tag>(endpoints.tags.root, { household_id: householdId, name, color })
    toast.success(t('tagCreate.created'))
    await navigate(routes.tags.list)
  }

  // Only offer a household choice when there is more than one; otherwise the
  // single household is used silently.
  const householdSelect =
    households.length > 1 ? (
      <div className="flex flex-col gap-1.5">
        <Label id="household-label" htmlFor="household">
          {t('tagCreate.household')}
        </Label>
        <Select
          value={householdId !== null ? String(householdId) : undefined}
          onValueChange={(v) => setHouseholdId(Number(v))}
        >
          <SelectTrigger id="household" aria-label={t('tagCreate.household')} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {households.map((h) => (
              <SelectItem key={h.id} value={String(h.id)}>
                {h.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    ) : null

  return (
    <main className="mx-auto w-full max-w-lg px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {t('tagCreate.title')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : households.length === 0 ? (
        <p className="font-medium text-muted-foreground">{error ?? t('tagCreate.noHouseholds')}</p>
      ) : (
        <>
          {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}
          <TagForm
            submitLabel={t('tagCreate.submit')}
            cancelTo={routes.tags.list}
            errorMessage={t('tagCreate.createError')}
            header={householdSelect}
            onSubmit={handleSubmit}
          />
        </>
      )}
    </main>
  )
}
