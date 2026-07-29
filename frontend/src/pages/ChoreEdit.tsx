import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { routes } from '../lib/routes'
import { ChoreForm, type ChoreSubmit } from '@/components/chores/ChoreForm'
import { Label } from '@/components/ui/label'
import type { Chore, HouseholdMember, Page, Tag } from '../lib/types'

export default function ChoreEdit() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { id = '' } = useParams()
  const [chore, setChore] = useState<Chore | null>(null)
  const [members, setMembers] = useState<HouseholdMember[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Load the chore, then its household's members and tags for the pickers.
  useEffect(() => {
    let cancelled = false
    api
      .get<Chore>(endpoints.chores.byId(id))
      .then((data) =>
        Promise.all([
          api.get<Page<HouseholdMember>>(
            `${endpoints.households.members(data.household.id)}?page_size=100`,
          ),
          // page_size=100 loads the whole household's tags for the picker.
          api.get<Page<Tag>>(
            `${endpoints.tags.root}?household_id=${data.household.id}&page_size=100&sort_by=name&sort_dir=asc`,
          ),
        ]).then(([membersPage, tagsPage]) => {
          if (cancelled) return
          setChore(data)
          setMembers(membersPage.items)
          setTags(tagsPage.items)
        }),
      )
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('choreEdit.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id, t])

  async function handleSubmit(values: ChoreSubmit) {
    await api.patch<Chore>(endpoints.chores.byId(id), values)
    toast.success(t('choreEdit.updated'))
    await navigate(routes.chores.list)
  }

  return (
    <main className="mx-auto w-full max-w-lg px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {t('choreEdit.title')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : !chore ? (
        <p className="text-[13px] font-bold text-danger">{error ?? t('choreEdit.notFound')}</p>
      ) : (
        <ChoreForm
          members={members}
          tags={tags}
          initial={{
            title: chore.title,
            description: chore.description ?? '',
            // '' is the form's spelling of "no start date" (an unscheduled chore); the
            // form hides the field and refills it if the period ever stops being manual.
            start_date: chore.start_date ?? '',
            repeats: chore.repeats,
            assignment_type: chore.assignment_type,
            turn_length: chore.turn_length,
            repeat_interval: chore.repeat_interval,
            weekdays: chore.weekdays ?? [],
            assignee_ids: chore.assignees.map((a) => a.id),
            current_assignee_id: chore.current_assignee?.id ?? null,
            // Seeded from the chore's actual state: an already-unassigned chore opens with
            // "Nobody in particular" selected rather than an empty picker, so saving an
            // unrelated edit cannot quietly re-derive an assignee for it.
            clear_current_assignee: chore.current_assignee === null,
            tag_ids: chore.tags.map((tag) => tag.id),
          }}
          submitLabel={t('choreEdit.submit')}
          cancelTo={routes.chores.list}
          errorMessage={t('choreEdit.updateError')}
          // Editing is where moving a chore off whoever is currently stuck with it
          // makes sense, whatever the strategy. Create leaves the auto strategies to
          // pick their own first assignee.
          allowAssigneeOverride
          header={
            <div className="flex flex-col gap-1.5">
              <Label>{t('choreCreate.household')}</Label>
              <p className="font-semibold">{chore.household.name}</p>
            </div>
          }
          onSubmit={handleSubmit}
        />
      )}
    </main>
  )
}
