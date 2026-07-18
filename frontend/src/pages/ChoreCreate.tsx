import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { todayISO } from '../lib/chores'
import { ChoreForm, type ChoreSubmit } from '@/components/chores/ChoreForm'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Chore, Household, HouseholdMember, Page, Tag } from '../lib/types'

export default function ChoreCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [households, setHouseholds] = useState<Household[]>([])
  const [householdId, setHouseholdId] = useState<number | null>(null)
  const [members, setMembers] = useState<HouseholdMember[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Load the user's households once; default the chore to the lowest-id one.
  useEffect(() => {
    let cancelled = false
    api
      .get<Page<Household>>('/api/v1/households?sort_by=id&sort_dir=asc&page_size=100')
      .then((page) => {
        if (cancelled) return
        setHouseholds(page.items)
        setHouseholdId(page.items[0]?.id ?? null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('choreCreate.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  // Load the selected household's members and tags for the assignee/tag pickers.
  useEffect(() => {
    if (householdId === null) return
    let cancelled = false
    Promise.all([
      api.get<Page<HouseholdMember>>(`/api/v1/households/${householdId}/members?page_size=100`),
      // page_size=100 loads the whole household's tags for the picker (same cap
      // the members/households pickers use).
      api.get<Page<Tag>>(
        `/api/v1/tags?household_id=${householdId}&page_size=100&sort_by=name&sort_dir=asc`,
      ),
    ])
      .then(([membersPage, tagsPage]) => {
        if (cancelled) return
        setMembers(membersPage.items)
        setTags(tagsPage.items)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('choreCreate.loadError'))
      })
    return () => {
      cancelled = true
    }
  }, [householdId, t])

  async function handleSubmit(values: ChoreSubmit) {
    await api.post<Chore>('/api/v1/chores', { household_id: householdId, ...values })
    toast.success(t('choreCreate.created'))
    await navigate('/chores')
  }

  // Only offer a household choice when there is more than one; otherwise the
  // single household is used silently.
  const householdSelect =
    households.length > 1 ? (
      <div className="flex flex-col gap-1.5">
        <Label id="household-label" htmlFor="household">
          {t('choreCreate.household')}
        </Label>
        <Select
          value={householdId !== null ? String(householdId) : undefined}
          onValueChange={(v) => setHouseholdId(Number(v))}
        >
          <SelectTrigger id="household" aria-label={t('choreCreate.household')} className="w-full">
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
        {t('choreCreate.title')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : households.length === 0 ? (
        <p className="font-medium text-muted-foreground">
          {error ?? t('choreCreate.noHouseholds')}
        </p>
      ) : (
        <>
          {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}
          <ChoreForm
            members={members}
            tags={tags}
            initial={{
              title: '',
              description: '',
              start_date: todayISO(),
              repeats: 'weekly',
              assignment_type: 'manual',
              assignee_ids: [],
              tag_ids: [],
            }}
            submitLabel={t('choreCreate.submit')}
            cancelTo="/chores"
            errorMessage={t('choreCreate.createError')}
            header={householdSelect}
            onSubmit={handleSubmit}
          />
        </>
      )}
    </main>
  )
}
