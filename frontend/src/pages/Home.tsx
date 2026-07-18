import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { useAuth } from '../auth/useAuth'
import { api, ApiError } from '../lib/api'
import { formatDateTime } from '../lib/format'
import { dueDotClass, relativeDueLabel, sortByDue } from '../lib/home'
import type { DueChore, HomeData } from '../lib/types'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

// One due chore: checkbox + title + a short due label / date / repeat + a
// colour-coded status dot. Module-local (not exported) so Home.tsx keeps a
// single default export (react-refresh only-export-components).
function DueRow({
  chore,
  t,
  onComplete,
}: {
  chore: DueChore
  t: TFunction
  onComplete: (chore: DueChore) => void
}) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-border bg-card p-3.5">
      <Checkbox
        aria-label={t('home.markDone', { title: chore.title })}
        onCheckedChange={() => onComplete(chore)}
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
      <span
        className={cn('inline-block size-2.5 shrink-0 rounded-full', dueDotClass(chore.status))}
        aria-hidden
      />
    </li>
  )
}

export default function Home() {
  const { user } = useAuth()
  const { t } = useTranslation()
  const [data, setData] = useState<HomeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<HomeData>('/api/v1/home')
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
  }, [t])

  async function handleComplete(chore: DueChore) {
    setError(null)
    // Optimistic: drop the row now (it "disappears" on check), and bump today's
    // progress if this was an overdue/due-today task. A "soon" chore completed
    // early doesn't move today's progress, matching the server. We don't refetch:
    // a repeating chore whose next occurrence lands within the window (daily ->
    // tomorrow, weekly -> +7d) would otherwise bounce straight back into the list.
    // Functional updates so overlapping completions compose (each only ever
    // touches its own row).
    const bump = chore.days_until_due <= 0 ? 1 : 0
    setData((d) =>
      d
        ? {
            progress: { ...d.progress, done_today: d.progress.done_today + bump },
            items: d.items.filter((item) => item.id !== chore.id),
          }
        : d,
    )
    try {
      await api.post(`/api/v1/chores/${chore.id}/complete`)
    } catch (err) {
      // Roll back just this chore (render re-sorts, so its position is restored).
      setData((d) =>
        d
          ? {
              progress: { ...d.progress, done_today: d.progress.done_today - bump },
              items: [...d.items, chore],
            }
          : d,
      )
      setError(err instanceof ApiError ? err.message : t('home.completeError'))
    }
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
            <ul className="mt-6 flex flex-col gap-2">
              {sortByDue(data.items).map((chore) => (
                <DueRow key={chore.id} chore={chore} t={t} onComplete={handleComplete} />
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
