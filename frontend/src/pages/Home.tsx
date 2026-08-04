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
import CreditDialog from '@/components/chores/CreditDialog'
import DescriptionDialog from '@/components/chores/DescriptionDialog'
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
  // Which chore's instructions are on screen; non-null opens the dialog, as with creditFor.
  const [descriptionFor, setDescriptionFor] = useState<DueChore | null>(null)
  // The chore awaiting a "really skip this?" confirmation (null = closed), same open-on-
  // non-null shape. Skipping always confirms, unlike completing: it moves the chore's
  // schedule on, and undo lives in History, which helpers cannot reach at all - so for them
  // an unconfirmed mis-click would be unrecoverable.
  const [skipFor, setSkipFor] = useState<DueChore | null>(null)

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

  // Completing and skipping both close the occurrence server-side, so they share every bit
  // of this: the exit animation, the double-click lock, the monotonic request guard and the
  // refetch. Only the request and the fallback error copy differ, and keeping them in one
  // function is what stops the animation timing and the guard drifting apart between them.
  function closeChore(chore: DueChore, request: () => Promise<unknown>, fallbackError: string) {
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

    let req = 0
    request()
      .then(() => {
        req = ++reqRef.current
        return Promise.all([fetchHomeRef.current(), animated])
      })
      .then(([home]) => {
        if (req === reqRef.current) setData(home)
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : fallbackError)
      })
      .finally(stopExiting)
  }

  function completeChore(chore: DueChore, completedByUserId?: number) {
    // Only send a body when crediting someone other than the current user; the
    // default (no body) credits the caller.
    const body =
      completedByUserId === undefined ? undefined : { completed_by_user_id: completedByUserId }
    closeChore(
      chore,
      () => api.post(endpoints.chores.complete(chore.id), body),
      t('home.completeError'),
    )
  }

  // No credit question for a skip: there is no work to attribute, so it is always recorded
  // against whoever confirmed it and the endpoint takes no body.
  function skipChore(chore: DueChore) {
    closeChore(chore, () => api.post(endpoints.chores.skip(chore.id)), t('home.skipError'))
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

  function confirmSkip() {
    const chore = skipFor
    setSkipFor(null)
    if (chore) skipChore(chore)
  }

  const left = data ? data.progress.total_today - data.progress.done_today : 0
  const pct =
    data && data.progress.total_today > 0
      ? Math.min(100, Math.round((data.progress.done_today / data.progress.total_today) * 100))
      : 0

  // Only label the household when the user actually spans more than one.
  const multiHousehold = options.households.length > 1

  // The heading is visible, styled and placed exactly as its Unscheduled twin's, so the two
  // chore feeds read as a pair. Spacing is a flex `gap` rather than per-block top margins,
  // because which block renders first depends on state: a `:first-child` scheme silently
  // re-flows the moment anything is added above it.
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-5 py-8">
      <h1 className="font-display text-2xl font-bold tracking-tight">{t('home.title')}</h1>

      {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

      <ChoreFilters
        group="home"
        options={options}
        householdId={householdId}
        onHouseholdChange={setHouseholdId}
        assigneeIds={assigneeIds}
        onAssigneeChange={setAssigneeIds}
      />

      {loading && !data && (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      )}

      {data && (
        <>
          {data.progress.total_today > 0 && (
            <div className="rounded-xl border border-border bg-card p-4">
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
            <ul className="flex flex-col">
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
                        descriptionLabel={t('home.showDescription', { title: chore.title })}
                        skipLabel={t('home.skip', { title: chore.title })}
                        onShowDescription={
                          chore.has_description ? () => setDescriptionFor(chore) : undefined
                        }
                        onSkip={() => setSkipFor(chore)}
                        onComplete={() => requestComplete(chore)}
                      />
                    ))}
                  </Fragment>
                )
              })}
            </ul>
          ) : (
            <div className="mt-4 text-center">
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

      {/* Inline rather than its own component, unlike CreditDialog: only this page skips, and
          one caller does not earn the indirection. Controlled the same way, on skipFor. */}
      <AlertDialog open={skipFor !== null} onOpenChange={(open) => !open && setSkipFor(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('home.skipConfirm', { title: skipFor?.title ?? '' })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t('home.skipConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmSkip}>
              {t('home.skipConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <DescriptionDialog chore={descriptionFor} onClose={() => setDescriptionFor(null)} />
    </main>
  )
}
