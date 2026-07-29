import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { repeatLabel } from '../lib/chores'
import { formatDateTime } from '../lib/format'
import { dueDotClass, groupByDue, relativeDueLabel } from '../lib/home'
import type { DueChore, HomeData } from '../lib/types'
import ChoreFilters from '@/components/chores/ChoreFilters'
import ChoreRow from '@/components/chores/ChoreRow'
import CreditDialog from '@/components/chores/CreditDialog'
import { useFilterOptions } from '@/components/chores/useFilterOptions'
import { fullName } from '@/lib/user'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

// How long the row's exit animation runs; the row is removed from the list once
// it finishes. Kept in sync with the `duration-[..]` classes on ChoreRow.
const EXIT_MS = 420

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
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

  const options = useFilterOptions()
  const [householdId, setHouseholdId] = useState('')
  // Default view: your chores + shared. Seed the assignee filter with yourself;
  // adding members widens it, clearing it shows the whole household.
  const [assigneeIds, setAssigneeIds] = useState<number[]>(() => (user ? [user.id] : []))

  // Monotonic request id so a slow response (a filter change or a completion
  // refetch) can't overwrite a newer one; only the latest applies.
  const reqRef = useRef(0)

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
    // from the server rather than guessing locally: a recurring chore reappears at
    // its next occurrence, at a date this page may no longer be showing.
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

  const left = data ? data.progress.total_today - data.progress.done_today : 0
  const pct =
    data && data.progress.total_today > 0
      ? Math.min(100, Math.round((data.progress.done_today / data.progress.total_today) * 100))
      : 0

  // Only label the household when the user actually spans more than one.
  const multiHousehold = options.households.length > 1

  // The page carries no heading: the sidebar already says which view this is, and the
  // filters are what the user reaches for. Which block comes first therefore depends on
  // state, so each top-level block drops its own top margin when it lands first
  // (`first:mt-0`) and sits flush against main's own py-8.
  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      {error && <p className="mt-4 text-[13px] font-bold text-danger first:mt-0">{error}</p>}

      <ChoreFilters
        group="home"
        options={options}
        householdId={householdId}
        onHouseholdChange={setHouseholdId}
        assigneeIds={assigneeIds}
        onAssigneeChange={setAssigneeIds}
        className="mt-6 first:mt-0"
      />

      {loading && !data && (
        <p className="mt-6 font-medium text-muted-foreground first:mt-0">{t('common.loading')}</p>
      )}

      {data && (
        <>
          {data.progress.total_today > 0 && (
            <div className="mt-6 rounded-xl border border-border bg-card p-4 first:mt-0">
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
            /* One list, not one per section: it stays a single list to a screen
               reader (the sections carry no heading to be labelled by), and
               ChoreRow's `last:mb-0` keeps resolving against the real final row. */
            <ul className="mt-6 flex flex-col first:mt-0">
              {groupByDue(data.items).map((group, i, all) => {
                // A section keeps its rows until the post-completion refetch, so
                // emptying one leaves the rule with nothing to divide for the
                // length of the animation. Collapse it alongside whichever side
                // is going away, or completing the only chore due today strands a
                // hairline above the first visible row and then snaps.
                const ruleExiting =
                  i > 0 &&
                  (all[i - 1].items.every((c) => exiting.has(c.id)) ||
                    group.items.every((c) => exiting.has(c.id)))
                return (
                  <Fragment key={group.key}>
                    {/* The rule between sections. Decoration, so aria-hidden
                        keeps it out of the list; margins rather than a flex gap,
                        because a gap is not animated away (see ChoreRow). */}
                    {i > 0 && (
                      <li
                        aria-hidden
                        data-exiting={ruleExiting || undefined}
                        className={cn(
                          'mt-2 mb-4 border-t border-border transition-[margin,opacity] duration-[420ms] ease-out motion-reduce:transition-none',
                          'data-[exiting]:mt-0 data-[exiting]:mb-0 data-[exiting]:opacity-0',
                        )}
                      />
                    )}
                    {group.items.map((chore) => (
                      <ChoreRow
                        key={chore.id}
                        title={chore.title}
                        dotClass={dueDotClass(chore)}
                        detail={`${relativeDueLabel(t, chore)} · ${formatDateTime(chore.next_due)} · ${repeatLabel(t, chore)}`}
                        assignee={
                          chore.assignees.length === 0
                            ? t('home.unassigned')
                            : chore.assignees.map(fullName).join(', ')
                        }
                        householdName={multiHousehold ? chore.household.name : undefined}
                        exiting={exiting.has(chore.id)}
                        doneText={t('home.done')}
                        doneLabel={t('home.markDone', { title: chore.title })}
                        onComplete={() => requestComplete(chore)}
                      />
                    ))}
                  </Fragment>
                )
              })}
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

      <CreditDialog
        group="home"
        chore={creditFor}
        onClose={() => setCreditFor(null)}
        onConfirm={creditAndComplete}
      />
    </main>
  )
}
