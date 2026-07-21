import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import { todayISO } from '../lib/chores'
import { ChoreForm, type ChoreFormValues, type ChoreSubmit } from '@/components/chores/ChoreForm'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Chore, ChoreCloneState, Household, HouseholdMember, Page, Tag } from '../lib/types'

export default function ChoreCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  // Present when arriving via a chore's "Clone" action: prefills the form and
  // defaults the household to the source chore's.
  const clone = (location.state as { clone?: ChoreCloneState } | null)?.clone
  const [households, setHouseholds] = useState<Household[]>([])
  const [householdId, setHouseholdId] = useState<number | null>(clone?.household_id ?? null)
  const [members, setMembers] = useState<HouseholdMember[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  // Which household the currently loaded members/tags belong to; gates the clone
  // drop note so it doesn't flash while a household's pickers are still loading.
  const [optionsHouseholdId, setOptionsHouseholdId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Load the user's households once; default the chore to the lowest-id one
  // (unless cloning already seeded the source chore's household).
  useEffect(() => {
    let cancelled = false
    api
      .get<Page<Household>>(`${endpoints.households.root}?sort_by=id&sort_dir=asc&page_size=100`)
      .then((page) => {
        if (cancelled) return
        setHouseholds(page.items)
        setHouseholdId((cur) => cur ?? page.items[0]?.id ?? null)
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
      api.get<Page<HouseholdMember>>(`${endpoints.households.members(householdId)}?page_size=100`),
      // page_size=100 loads the whole household's tags for the picker (same cap
      // the members/households pickers use).
      api.get<Page<Tag>>(
        `${endpoints.tags.root}?household_id=${householdId}&page_size=100&sort_by=name&sort_dir=asc`,
      ),
    ])
      .then(([membersPage, tagsPage]) => {
        if (cancelled) return
        setMembers(membersPage.items)
        setTags(tagsPage.items)
        setOptionsHouseholdId(householdId)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('choreCreate.loadError'))
      })
    return () => {
      cancelled = true
    }
  }, [householdId, t])

  async function handleSubmit(values: ChoreSubmit) {
    await api.post<Chore>(endpoints.chores.root, { household_id: householdId, ...values })
    toast.success(t('choreCreate.created'))
    await navigate(routes.chores.list)
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

  // Prefilled values when cloning; empty defaults otherwise. ChoreForm lazy-inits
  // from this and the form mounts only after households load, so clone values are
  // ready in time.
  const initial: ChoreFormValues = {
    title: clone?.title ?? '',
    description: clone?.description ?? '',
    start_date: clone?.start_date ?? todayISO(),
    repeats: clone?.repeats ?? 'weekly',
    assignment_type: clone?.assignment_type ?? 'manual',
    turn_length: clone?.turn_length ?? 1,
    assignee_ids: clone?.assignee_ids ?? [],
    // A fresh chore derives its own starting assignee (manual lets you pick one).
    current_assignee_id: null,
    tag_ids: clone?.tag_ids ?? [],
  }

  // How many cloned assignees/tags don't belong to the selected household and so
  // won't be added. Gated on optionsHouseholdId so it reflects loaded pickers.
  const memberIdSet = new Set(members.map((m) => m.id))
  const tagIdSet = new Set(tags.map((tag) => tag.id))
  const droppedAssignees = clone
    ? clone.assignee_ids.filter((id) => !memberIdSet.has(id)).length
    : 0
  const droppedTags = clone ? clone.tag_ids.filter((id) => !tagIdSet.has(id)).length : 0
  const showDrop = optionsHouseholdId === householdId && (droppedAssignees > 0 || droppedTags > 0)

  const header = (
    <>
      {householdSelect}
      {showDrop && (
        <div
          role="status"
          className="rounded-input border border-line bg-muted p-3 text-[13px] font-medium text-muted-foreground"
        >
          {droppedAssignees > 0 && (
            <p>{t('choreCreate.cloneDroppedAssignees', { count: droppedAssignees })}</p>
          )}
          {droppedTags > 0 && <p>{t('choreCreate.cloneDroppedTags', { count: droppedTags })}</p>}
        </div>
      )}
    </>
  )

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
            initial={initial}
            submitLabel={t('choreCreate.submit')}
            cancelTo={routes.chores.list}
            errorMessage={t('choreCreate.createError')}
            header={header}
            onSubmit={handleSubmit}
          />
        </>
      )}
    </main>
  )
}
