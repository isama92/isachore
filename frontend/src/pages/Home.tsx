import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { CheckIcon } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { formatDateTime } from '../lib/format'
import { dueDotClass, relativeDueLabel, sortByDue } from '../lib/home'
import { fullName } from '../lib/user'
import type { DueChore, HistoryFilterOptions, HomeData } from '../lib/types'
import { AssigneeMultiSelect } from '@/components/home/AssigneeMultiSelect'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

// How long the row's exit animation runs; the row is removed from the list once
// it finishes. Kept in sync with the `duration-[..]` classes on DueRow.
const EXIT_MS = 420

// Radix Selects can't hold an empty value, so the "all" option uses a sentinel
// that maps back to an omitted filter (same pattern as History).
const ALL = 'all'

const EMPTY_OPTIONS: HistoryFilterOptions = { households: [], members: [] }

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

// One due chore: a colour-coded status dot + title + a short due label / date /
// repeat, the assignee ("who is this for"), and a "Done" button. On completion
// the row plays an exit animation driven by `exiting`, so the rows below glide
// up. Module-local (not exported) so Home.tsx keeps a single default export
// (react-refresh only-export-components).
function DueRow({
  chore,
  t,
  exiting,
  onComplete,
}: {
  chore: DueChore
  t: TFunction
  exiting: boolean
  onComplete: (chore: DueChore) => void
}) {
  const assignee =
    chore.assignees.length === 0 ? t('home.unassigned') : chore.assignees.map(fullName).join(', ')
  return (
    <li
      data-exiting={exiting || undefined}
      className={cn(
        'group grid grid-rows-[1fr] mb-2 transition-[grid-template-rows,opacity,margin] duration-[420ms] ease-out last:mb-0 motion-reduce:transition-none',
        'data-[exiting]:pointer-events-none data-[exiting]:mb-0 data-[exiting]:grid-rows-[0fr] data-[exiting]:opacity-0',
      )}
    >
      <div className="overflow-hidden">
        <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-3.5 transition-transform duration-[420ms] ease-out group-data-[exiting]:-translate-x-3 group-data-[exiting]:scale-[0.97] motion-reduce:transition-none">
          <span
            className={cn('inline-block size-2.5 shrink-0 rounded-full', dueDotClass(chore.status))}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">{chore.title}</p>
            <p className="mt-0.5 text-[13px] font-medium text-muted-foreground">
              {relativeDueLabel(t, chore)}
              {' · '}
              {formatDateTime(chore.next_due)}
              {' · '}
              {t(`options.repeat.${chore.repeats}`)}
            </p>
          </div>
          <span className="hidden max-w-[9rem] shrink-0 truncate text-[13px] font-medium text-muted-foreground sm:inline">
            {assignee}
          </span>
          {/* Outline pill in the active accent (--primary) that fills on hover. */}
          <Button
            type="button"
            variant="ghost"
            disabled={exiting}
            aria-label={t('home.markDone', { title: chore.title })}
            onClick={() => onComplete(chore)}
            className="shrink-0 border-primary text-primary hover:bg-primary hover:text-primary-foreground hover:shadow-glow dark:hover:bg-primary"
          >
            <CheckIcon />
            {t('home.done')}
          </Button>
        </div>
      </div>
    </li>
  )
}

export default function Home() {
  const { user } = useAuth()
  const { t } = useTranslation()
  const [data, setData] = useState<HomeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Ids of rows currently playing their exit animation.
  const [exiting, setExiting] = useState<Set<number>>(new Set())
  // The chore whose "who gets credit" dialog is open (null = closed). Only shown
  // when completing a chore assigned to someone other than the current user.
  const [creditFor, setCreditFor] = useState<DueChore | null>(null)

  const [options, setOptions] = useState<HistoryFilterOptions>(EMPTY_OPTIONS)
  const [householdId, setHouseholdId] = useState('')
  // Default view: your chores + shared. Seed the assignee filter with yourself;
  // adding members widens it, clearing it shows the whole household.
  const [assigneeIds, setAssigneeIds] = useState<number[]>(() => (user ? [user.id] : []))

  // Monotonic request id so a slow response (a filter change or a completion
  // refetch) can't overwrite a newer one; only the latest applies.
  const reqRef = useRef(0)

  // The household + member option lists for the filters (shared with History).
  useEffect(() => {
    let cancelled = false
    api
      .get<HistoryFilterOptions>(endpoints.completions.filters)
      .then((opts) => {
        if (!cancelled) setOptions(opts)
      })
      .catch(() => {
        if (!cancelled) setOptions(EMPTY_OPTIONS)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // The current query URL: the filters are per-request state appended to the path.
  const query = useMemo(() => {
    const params = new URLSearchParams()
    if (householdId) params.set('household_id', householdId)
    for (const id of assigneeIds) params.append('assignee_id', String(id))
    const qs = params.toString()
    return qs ? `${endpoints.home}?${qs}` : endpoints.home
  }, [householdId, assigneeIds])

  const fetchHome = useCallback(() => api.get<HomeData>(query), [query])

  // The post-completion refetch reads the latest fetch via this ref, so
  // completing a chore and then changing a filter within the animation window
  // still reconciles against the currently selected filters (not the ones
  // captured at click time).
  const fetchHomeRef = useRef(fetchHome)
  useEffect(() => {
    fetchHomeRef.current = fetchHome
  }, [fetchHome])

  useEffect(() => {
    let cancelled = false
    const req = ++reqRef.current
    fetchHome()
      .then((home) => {
        if (!cancelled && req === reqRef.current) setData(home)
      })
      .catch(() => {
        if (!cancelled) setError(t('home.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [fetchHome, t])

  function completeChore(chore: DueChore, completedByUserId?: number) {
    if (exiting.has(chore.id)) return // ignore repeat clicks while a row animates out
    setError(null)
    // Play the exit animation for responsiveness, then reconcile the whole view
    // from the server rather than guessing locally: a completed one-off
    // disappears and a recurring chore reappears at its next occurrence.
    setExiting((s) => new Set(s).add(chore.id))

    const stopExiting = () =>
      setExiting((s) => {
        const next = new Set(s)
        next.delete(chore.id)
        return next
      })
    const animated = new Promise<void>((resolve) => {
      window.setTimeout(resolve, prefersReducedMotion() ? 0 : EXIT_MS)
    })

    // Only send a body when crediting someone other than the current user; the
    // default (no body) credits the caller.
    const body =
      completedByUserId === undefined ? undefined : { completed_by_user_id: completedByUserId }
    let req = 0
    api
      .post(endpoints.chores.complete(chore.id), body)
      .then(() => {
        req = ++reqRef.current
        return Promise.all([fetchHomeRef.current(), animated])
      })
      .then(([home]) => {
        if (req === reqRef.current) setData(home)
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : t('home.completeError'))
      })
      .finally(stopExiting)
  }

  // Clicking Done: an unassigned chore, or one I'm already an assignee of,
  // completes straight away (credited to me). A chore assigned only to other
  // members opens the credit dialog so I can choose who the History records.
  function requestComplete(chore: DueChore) {
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

  const isPersonal = !!user && assigneeIds.length === 1 && assigneeIds[0] === user.id
  const heading = isPersonal ? t('home.titleMine') : t('home.titleHousehold')
  const left = data ? data.progress.total_today - data.progress.done_today : 0
  const pct =
    data && data.progress.total_today > 0
      ? Math.min(100, Math.round((data.progress.done_today / data.progress.total_today) * 100))
      : 0

  const showFilters = options.households.length > 1 || options.members.length > 1

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      <h1 className="font-display text-2xl font-bold tracking-tight">{heading}</h1>

      {error && <p className="mt-4 text-[13px] font-bold text-danger">{error}</p>}

      {showFilters && (
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          {options.households.length > 1 && (
            <Select
              value={householdId || ALL}
              onValueChange={(v) => setHouseholdId(v === ALL ? '' : v)}
            >
              <SelectTrigger className="sm:w-56" aria-label={t('home.filters.householdLabel')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>{t('home.filters.householdAll')}</SelectItem>
                {options.households.map((h) => (
                  <SelectItem key={h.id} value={String(h.id)}>
                    {h.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {options.members.length > 1 && (
            <AssigneeMultiSelect
              members={options.members}
              value={assigneeIds}
              onChange={setAssigneeIds}
              label={t('home.filters.assigneeLabel')}
              placeholder={t('home.filters.assigneeAll')}
              searchPlaceholder={t('home.filters.assigneeSearch')}
              emptyText={t('home.filters.assigneeEmpty')}
              className="sm:w-56"
            />
          )}
        </div>
      )}

      {loading && !data && (
        <p className="mt-6 font-medium text-muted-foreground">{t('common.loading')}</p>
      )}

      {data && (
        <>
          {data.progress.total_today > 0 && (
            <div className="mt-6 rounded-xl border border-border bg-card p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className="font-semibold">
                  {t('home.progress.doneToday', {
                    done: data.progress.done_today,
                    total: data.progress.total_today,
                  })}
                </span>
                <span className="shrink-0 text-[13px] font-medium text-muted-foreground">
                  {t('home.progress.left', { count: left })}
                </span>
              </div>
              <Progress value={pct} />
            </div>
          )}

          {data.items.length > 0 ? (
            <ul className="mt-6 flex flex-col">
              {sortByDue(data.items).map((chore) => (
                <DueRow
                  key={chore.id}
                  chore={chore}
                  t={t}
                  exiting={exiting.has(chore.id)}
                  onComplete={requestComplete}
                />
              ))}
            </ul>
          ) : (
            <div className="mt-10 text-center">
              <p className="font-display text-lg font-bold tracking-tight">
                {t('home.emptyTitle')}
              </p>
              <p className="mt-1 font-medium text-muted-foreground">{t('home.emptyHint')}</p>
            </div>
          )}
        </>
      )}

      <AlertDialog open={creditFor !== null} onOpenChange={(open) => !open && setCreditFor(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('home.credit.title', { title: creditFor?.title ?? '' })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('home.credit.body', {
                names: creditFor ? creditFor.assignees.map(fullName).join(', ') : '',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            {creditFor?.assignees.map((a) => (
              <AlertDialogAction key={a.id} onClick={() => creditAndComplete(a.id)}>
                {t('home.credit.doneAs', { name: fullName(a) })}
              </AlertDialogAction>
            ))}
            <AlertDialogAction onClick={() => creditAndComplete()}>
              {t('home.credit.doneAsMe')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  )
}
