import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { doneDotClass, lastDoneLabel } from '../lib/unscheduled'
import type { UnscheduledChore, UnscheduledData } from '../lib/types'
import ChoreFilters from '@/components/chores/ChoreFilters'
import ChoreRow from '@/components/chores/ChoreRow'
import CreditDialog from '@/components/chores/CreditDialog'
import DescriptionDialog from '@/components/chores/DescriptionDialog'
import { useFilterOptions } from '@/components/chores/useFilterOptions'
import { fullName } from '@/lib/user'

export default function Unscheduled() {
  const { user } = useAuth()
  const { t } = useTranslation()
  const [data, setData] = useState<UnscheduledData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Ids of chores whose completion is in flight. Unlike the due view there is no exit
  // animation to drive: the chore reopens immediately, so the row stays and only its
  // "last done" line changes. This just keeps the button from submitting twice.
  const [busy, setBusy] = useState<Set<number>>(new Set())
  // The chore whose "who gets credit" dialog is open (null = closed).
  const [creditFor, setCreditFor] = useState<UnscheduledChore | null>(null)
  // Which chore's instructions are on screen; non-null opens the dialog, as with creditFor.
  const [descriptionFor, setDescriptionFor] = useState<UnscheduledChore | null>(null)

  const options = useFilterOptions()
  const [householdId, setHouseholdId] = useState('')
  // Same default as the due view: your chores + shared, widened by adding members.
  const [assigneeIds, setAssigneeIds] = useState<number[]>(() => (user ? [user.id] : []))

  // Monotonic request id so a slow response (a filter change or a completion refetch)
  // can't overwrite a newer one; only the latest applies.
  const reqRef = useRef(0)

  const query = useMemo(() => {
    const params = new URLSearchParams()
    if (householdId) params.set('household_id', householdId)
    for (const id of assigneeIds) params.append('assignee_id', String(id))
    const qs = params.toString()
    return qs ? `${endpoints.unscheduled}?${qs}` : endpoints.unscheduled
  }, [householdId, assigneeIds])

  const fetchList = useCallback(() => api.get<UnscheduledData>(query), [query])

  // The post-completion refetch reads the latest fetch through this ref, so completing a
  // chore and then changing a filter still reconciles against the current filters.
  const fetchListRef = useRef(fetchList)
  useEffect(() => {
    fetchListRef.current = fetchList
  }, [fetchList])

  useEffect(() => {
    let cancelled = false
    const req = ++reqRef.current
    fetchList()
      .then((list) => {
        if (!cancelled && req === reqRef.current) setData(list)
      })
      .catch(() => {
        if (!cancelled) setError(t('unscheduled.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [fetchList, t])

  function completeChore(chore: UnscheduledChore, completedByUserId?: number) {
    if (busy.has(chore.id)) return // ignore repeat clicks while one is in flight
    setError(null)
    setBusy((s) => new Set(s).add(chore.id))

    // Only send a body when crediting someone other than the current user; the default
    // (no body) credits the caller.
    const body =
      completedByUserId === undefined ? undefined : { completed_by_user_id: completedByUserId }
    let req = 0
    api
      .post(endpoints.chores.complete(chore.id), body)
      .then(() => {
        // A toast is the feedback here, because the row itself does not go anywhere: it
        // stays put and re-reads "Last done today" once the refetch lands.
        toast.success(t('unscheduled.completed'))
        req = ++reqRef.current
        return fetchListRef.current()
      })
      .then((list) => {
        if (req === reqRef.current) setData(list)
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : t('unscheduled.completeError'))
      })
      .finally(() =>
        setBusy((s) => {
          const next = new Set(s)
          next.delete(chore.id)
          return next
        }),
      )
  }

  // Same rule as the due view: an unassigned chore, or one I am an assignee of, completes
  // straight away; one assigned only to others asks who to credit.
  function requestComplete(chore: UnscheduledChore) {
    const mine = user ? chore.assignees.some((a) => a.id === user.id) : false
    if (chore.assignees.length === 0 || mine) {
      completeChore(chore)
    } else {
      setCreditFor(chore)
    }
  }

  function creditAndComplete(completedByUserId?: number) {
    const chore = creditFor
    setCreditFor(null)
    if (chore) completeChore(chore, completedByUserId)
  }

  // Only label the household when the user actually spans more than one.
  const multiHousehold = options.households.length > 1

  // Same flex-gap flow as the due view, so the twin pages stay in step; this one shows its
  // heading, since it is the view you arrive at deliberately rather than the landing page.
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-5 py-8">
      <h1 className="font-display text-2xl font-bold tracking-tight">{t('unscheduled.title')}</h1>

      {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

      <ChoreFilters
        group="unscheduled"
        options={options}
        householdId={householdId}
        onHouseholdChange={setHouseholdId}
        assigneeIds={assigneeIds}
        onAssigneeChange={setAssigneeIds}
      />

      {loading && !data && (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      )}

      {data &&
        (data.items.length > 0 ? (
          // A flat list: no due sections to divide, because nothing here is due. The
          // server orders it alphabetically.
          <ul className="flex flex-col">
            {data.items.map((chore) => (
              <ChoreRow
                key={chore.id}
                title={chore.title}
                dotClass={doneDotClass(chore)}
                detail={lastDoneLabel(t, chore)}
                assignee={
                  chore.assignees.length === 0
                    ? t('unscheduled.unassigned')
                    : chore.assignees.map(fullName).join(', ')
                }
                householdName={multiHousehold ? chore.household.name : undefined}
                busy={busy.has(chore.id)}
                doneText={t('unscheduled.done')}
                doneLabel={t('unscheduled.markDone', { title: chore.title })}
                descriptionLabel={t('unscheduled.showDescription', { title: chore.title })}
                onShowDescription={
                  chore.has_description ? () => setDescriptionFor(chore) : undefined
                }
                onComplete={() => requestComplete(chore)}
              />
            ))}
          </ul>
        ) : (
          <div className="mt-4 text-center">
            <p className="font-display text-lg font-bold tracking-tight">
              {t('unscheduled.emptyTitle')}
            </p>
            <p className="mt-1 font-medium text-muted-foreground">{t('unscheduled.emptyHint')}</p>
          </div>
        ))}

      <CreditDialog
        group="unscheduled"
        chore={creditFor}
        onClose={() => setCreditFor(null)}
        onConfirm={creditAndComplete}
      />

      <DescriptionDialog chore={descriptionFor} onClose={() => setDescriptionFor(null)} />
    </main>
  )
}
