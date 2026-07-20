import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { CheckIcon } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { formatDateTime } from '../lib/format'
import { dueDotClass, relativeDueLabel, sortByDue } from '../lib/home'
import type { DueChore, HomeData } from '../lib/types'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

// How long the row's exit animation runs; the row is removed from the list once
// it finishes. Kept in sync with the `duration-[..]` classes on DueRow.
const EXIT_MS = 420

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

// One due chore: a colour-coded status dot + title + a short due label / date /
// repeat + a "Done" button. On completion the row plays an exit animation
// (fade + slide + height-collapse) driven by `exiting`, so the rows below glide
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
  // Monotonic request id so a slow refetch response can't overwrite a newer one
  // when completions overlap; only the latest refetch is applied.
  const reqRef = useRef(0)

  const fetchHome = useCallback(() => api.get<HomeData>(endpoints.home), [])

  useEffect(() => {
    let cancelled = false
    fetchHome()
      .then((home) => {
        if (!cancelled) setData(home)
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

  function handleComplete(chore: DueChore) {
    if (exiting.has(chore.id)) return // ignore repeat clicks while a row animates out
    setError(null)
    // Play the exit animation for responsiveness, then reconcile the whole view
    // from the server rather than guessing locally: a completed one-off
    // disappears and a recurring chore reappears at its next occurrence, exactly
    // as a fresh page load would.
    setExiting((s) => new Set(s).add(chore.id))

    const stopExiting = () =>
      setExiting((s) => {
        const next = new Set(s)
        next.delete(chore.id)
        return next
      })
    // Resolves once the exit animation has run, so the row finishes gliding away
    // before the refetched list replaces it (even when the network is fast).
    const animated = new Promise<void>((resolve) => {
      window.setTimeout(resolve, prefersReducedMotion() ? 0 : EXIT_MS)
    })

    // Sequence the refetch, not the click: the latest refetch to be *issued*
    // (each after its completion has committed) wins, so overlapping completions
    // converge on the freshest snapshot regardless of response order.
    let req = 0
    api
      .post(endpoints.chores.complete(chore.id))
      .then(() => {
        req = ++reqRef.current
        return Promise.all([fetchHome(), animated])
      })
      .then(([home]) => {
        if (req === reqRef.current) setData(home)
      })
      .catch((err: unknown) => {
        // Leave `data` untouched so the row simply un-collapses back in place.
        setError(err instanceof ApiError ? err.message : t('home.completeError'))
      })
      .finally(stopExiting)
  }

  const greeting = user ? t('home.greeting', { name: user.first_name }) : 'isachore'
  const left = data ? data.progress.total_today - data.progress.done_today : 0
  const pct =
    data && data.progress.total_today > 0
      ? Math.min(100, Math.round((data.progress.done_today / data.progress.total_today) * 100))
      : 0

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-8">
      <h1 className="font-display text-2xl font-bold tracking-tight">{greeting}</h1>

      {error && <p className="mt-4 text-[13px] font-bold text-danger">{error}</p>}

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
                  onComplete={handleComplete}
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
    </main>
  )
}
