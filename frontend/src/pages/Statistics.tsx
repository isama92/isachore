import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, XAxis, YAxis } from 'recharts'
import { useAuth } from '../auth/useAuth'
import { api } from '../lib/api'
import { householdIdsWithRole } from '../lib/permissions'
import { endpoints } from '../lib/endpoints'
import { formatDate } from '../lib/chores'
import { fullName } from '../lib/user'
import type { HistoryFilterOptions, StatsData, StatsRange } from '../lib/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

// Radix Selects can't hold an empty value, so the "all" option uses a sentinel
// that maps back to an omitted filter (same pattern as the History page).
const ALL = 'all'
const RANGES: readonly StatsRange[] = ['7d', '30d', '90d']
const RANGE_DAYS: Record<StatsRange, number> = { '7d': 7, '30d': 30, '90d': 90 }
const EMPTY_OPTIONS: HistoryFilterOptions = { households: [], members: [] }

type Filters = { user_id: string; household_id: string }
type Slice = { key: string; label: string; value: number; color: string }

// A big headline number with its caption. No plot, so no chart machinery.
function KpiCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-1">
        <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </span>
        <span className="font-display text-2xl font-bold tabular-nums">{value}</span>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </CardContent>
    </Card>
  )
}

// A donut of parts-of-a-whole with an HTML legend that carries the labels and
// exact counts (so identity is never colour-alone, and the values are readable
// text rather than an SVG hover). The arc is drawn by Recharts.
function DonutCard({
  title,
  slices,
  emptyLabel,
}: {
  title: string
  slices: Slice[]
  emptyLabel: string
}) {
  const total = slices.reduce((sum, s) => sum + s.value, 0)
  const config = Object.fromEntries(slices.map((s) => [s.key, { label: s.label }])) as ChartConfig
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">{emptyLabel}</p>
        ) : (
          <div className="flex flex-col items-center gap-5 sm:flex-row sm:justify-center">
            <ChartContainer config={config} className="aspect-square h-[170px]">
              <PieChart>
                <ChartTooltip content={<ChartTooltipContent nameKey="key" hideLabel />} />
                <Pie
                  data={slices}
                  dataKey="value"
                  nameKey="key"
                  innerRadius={44}
                  strokeWidth={2}
                  isAnimationActive={false}
                >
                  {slices.map((s) => (
                    <Cell key={s.key} fill={s.color} />
                  ))}
                </Pie>
              </PieChart>
            </ChartContainer>
            <ul className="flex flex-col gap-2 text-sm">
              {slices.map((s) => (
                <li key={s.key} className="flex items-center gap-2">
                  <span
                    className="size-3 shrink-0 rounded-[3px]"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className="text-muted-foreground">{s.label}</span>
                  <span className="ml-auto pl-6 font-semibold tabular-nums">{s.value}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Statistics() {
  const { t } = useTranslation()
  const [range, setRange] = useState<StatsRange>('30d')
  const [filters, setFilters] = useState<Filters>({ user_id: '', household_id: '' })
  const [data, setData] = useState<StatsData | null>(null)
  const { memberships } = useAuth()
  // The households this page has data for. /completions/filters is deliberately NOT
  // role-narrowed (it also feeds the Home and Unscheduled filter bars, which every role
  // uses), so the narrowing happens here instead - otherwise the picker would offer a
  // household the caller is only a helper in and selecting it would come back empty.
  //
  // The "Completed by" picker keeps that dead end: it still lists members of helper-only
  // households, and the payload carries no member -> household association to narrow it by.
  // Nothing leaks (those names are already on Home), but do not read this as complete.
  const visible = useMemo(() => householdIdsWithRole(memberships, 'deputy'), [memberships])
  const [options, setOptions] = useState<HistoryFilterOptions>(EMPTY_OPTIONS)
  const [error, setError] = useState<string | null>(null)

  // Filter option lists (households + members), fetched once. Reused from the
  // History endpoint, so the two pages offer the same person/household filters.
  useEffect(() => {
    let cancelled = false
    api
      .get<HistoryFilterOptions>(endpoints.completions.filters)
      .then((d) => {
        if (!cancelled) {
          setOptions({ ...d, households: d.households.filter((h) => visible.has(h.id)) })
        }
      })
      .catch(() => {
        if (!cancelled) setOptions(EMPTY_OPTIONS)
      })
    return () => {
      cancelled = true
    }
  }, [visible])

  // The aggregated stats, refetched whenever the range or a filter changes.
  useEffect(() => {
    let cancelled = false
    const params = new URLSearchParams({ range })
    if (filters.user_id) params.set('user_id', filters.user_id)
    if (filters.household_id) params.set('household_id', filters.household_id)
    api
      .get<StatsData>(`${endpoints.stats}?${params.toString()}`)
      .then((d) => {
        if (!cancelled) {
          setData(d)
          setError(null)
        }
      })
      .catch(() => {
        // A load failure here is server-side (the params are fixed / validated),
        // so show the generic message like the History table does.
        if (!cancelled) setError(t('statistics.loadError'))
      })
    return () => {
      cancelled = true
    }
  }, [range, filters, t])

  const formatBucket = (iso: string) => formatDate(iso)

  const overTimeConfig = {
    count: {
      label: t('statistics.overTime.done'),
      // The theme's main colour (tracks the user's chosen accent).
      color: 'var(--color-primary)',
    },
    skipped: {
      label: t('statistics.overTime.skipped'),
      // Grey, not a second accent: this series is the absence of work, and it matches the
      // Skip button that produces it. Also what keeps it legible stacked on any --primary.
      color: 'var(--color-stat-skipped)',
    },
  } satisfies ChartConfig

  const rate = data?.kpis.on_time_rate
  const rateDisplay = rate == null ? t('statistics.kpis.noData') : `${Math.round(rate * 100)}%`

  const statusSlices: Slice[] = data
    ? [
        {
          key: 'overdue',
          label: t('statistics.statusDonut.overdue'),
          value: data.status_breakdown.overdue,
          color: 'var(--color-due-overdue)',
        },
        {
          key: 'today',
          label: t('statistics.statusDonut.today'),
          value: data.status_breakdown.today,
          color: 'var(--color-due-today)',
        },
        {
          key: 'soon',
          label: t('statistics.statusDonut.soon'),
          value: data.status_breakdown.soon,
          color: 'var(--color-due-soon)',
        },
      ]
    : []

  const punctualitySlices: Slice[] = data
    ? [
        {
          key: 'on_time',
          label: t('statistics.punctuality.onTime'),
          value: data.punctuality.on_time,
          color: 'var(--color-stat-on-time)',
        },
        {
          key: 'late',
          label: t('statistics.punctuality.late'),
          value: data.punctuality.late,
          color: 'var(--color-stat-late)',
        },
        {
          key: 'early',
          label: t('statistics.punctuality.early'),
          value: data.punctuality.early,
          color: 'var(--color-stat-early)',
        },
        // A skip had a real deadline (the API refuses to skip an unscheduled chore) but no
        // work to be punctual about, so it belongs here as its own outcome rather than being
        // folded into one of the three above. With it the four slices really do partition the
        // scheduled occurrences that closed in the range.
        {
          key: 'skipped',
          label: t('statistics.punctuality.skipped'),
          value: data.punctuality.skipped,
          color: 'var(--color-stat-skipped)',
        },
      ]
    : []

  // Both series, or a range containing nothing but skips would render the empty state.
  const overTimeTotal =
    data?.completions_over_time.reduce((sum, b) => sum + b.count + b.skipped, 0) ?? 0
  const perPersonMax = Math.max(1, ...(data?.per_person.map((p) => p.count) ?? [1]))

  return (
    <main className="mx-auto w-full max-w-5xl px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {t('statistics.title')}
      </h1>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <ToggleGroup
          type="single"
          value={range}
          onValueChange={(v) => v && setRange(v as StatsRange)}
          variant="outline"
          aria-label={t('statistics.range.label')}
        >
          {RANGES.map((r) => (
            <ToggleGroupItem key={r} value={r}>
              {t(`statistics.range.${r}`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        {options.members.length > 1 && (
          <Select
            value={filters.user_id || ALL}
            onValueChange={(v) => setFilters((f) => ({ ...f, user_id: v === ALL ? '' : v }))}
          >
            <SelectTrigger className="sm:w-56" aria-label={t('statistics.filters.userLabel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('statistics.filters.userAll')}</SelectItem>
              {options.members.map((m) => (
                <SelectItem key={m.id} value={String(m.id)}>
                  {fullName(m)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {options.households.length > 1 && (
          <Select
            value={filters.household_id || ALL}
            onValueChange={(v) => setFilters((f) => ({ ...f, household_id: v === ALL ? '' : v }))}
          >
            <SelectTrigger className="sm:w-56" aria-label={t('statistics.filters.householdLabel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('statistics.filters.householdAll')}</SelectItem>
              {options.households.map((h) => (
                <SelectItem key={h.id} value={String(h.id)}>
                  {h.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}

      {!data && !error && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-[300px] rounded-xl" />
          <div className="grid gap-6 sm:grid-cols-2">
            <Skeleton className="h-[260px] rounded-xl" />
            <Skeleton className="h-[260px] rounded-xl" />
          </div>
          <Skeleton className="h-[220px] rounded-xl" />
        </div>
      )}

      {data && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {/* The skip count rides in the hint rather than taking a fifth tile, which would
                leave an orphan in both the 2- and 4-column layouts. Two keys rather than a
                conditional inside one, per the i18n convention, and the plain hint stays for
                the common case of nothing skipped. */}
            <KpiCard
              label={t('statistics.kpis.completed')}
              value={String(data.kpis.completed_in_range)}
              hint={
                data.kpis.skipped_in_range > 0
                  ? // `count`, not `skipped`: i18next only pluralises on that name, and
                    // Italian needs "1 saltata" against "2 saltate".
                    t('statistics.kpis.completedHintSkipped', {
                      days: RANGE_DAYS[range],
                      count: data.kpis.skipped_in_range,
                    })
                  : t('statistics.kpis.completedHint', { days: RANGE_DAYS[range] })
              }
            />
            <KpiCard
              label={t('statistics.kpis.overdue')}
              value={String(data.kpis.currently_overdue)}
            />
            <KpiCard label={t('statistics.kpis.onTimeRate')} value={rateDisplay} />
            <KpiCard
              label={t('statistics.kpis.activeChores')}
              value={String(data.kpis.active_chores)}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t('statistics.overTime.title')}</CardTitle>
            </CardHeader>
            <CardContent>
              {overTimeTotal === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  {t('statistics.empty')}
                </p>
              ) : (
                <ChartContainer config={overTimeConfig} className="h-[240px] w-full">
                  <BarChart
                    data={data.completions_over_time}
                    margin={{ left: -12, right: 8, top: 8 }}
                  >
                    <CartesianGrid vertical={false} />
                    <XAxis
                      dataKey="bucket"
                      tickLine={false}
                      axisLine={false}
                      tickMargin={8}
                      minTickGap={24}
                      tickFormatter={formatBucket}
                    />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={32} />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent labelFormatter={(v) => formatBucket(String(v))} />
                      }
                    />
                    <ChartLegend content={<ChartLegendContent />} />
                    {/* Stacked, so each bar is the day's whole activity and the grey part
                        reads as the share that was skipped. The rounding is split across the
                        two so only the top of the stack is curved; a bucket with no skips
                        keeps square top corners, which is a cosmetic wrinkle we accept
                        rather than measuring each bar to decide. */}
                    <Bar
                      dataKey="count"
                      stackId="activity"
                      fill="var(--color-count)"
                      radius={[0, 0, 4, 4]}
                      isAnimationActive={false}
                    />
                    <Bar
                      dataKey="skipped"
                      stackId="activity"
                      fill="var(--color-skipped)"
                      radius={[4, 4, 0, 0]}
                      isAnimationActive={false}
                    />
                  </BarChart>
                </ChartContainer>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-6 sm:grid-cols-2">
            <DonutCard
              title={t('statistics.statusDonut.title')}
              slices={statusSlices}
              emptyLabel={t('statistics.empty')}
            />
            <DonutCard
              title={t('statistics.punctuality.title')}
              slices={punctualitySlices}
              emptyLabel={t('statistics.empty')}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t('statistics.perPerson.title')}</CardTitle>
            </CardHeader>
            <CardContent>
              {data.per_person.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  {t('statistics.empty')}
                </p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {data.per_person.map((p) => (
                    <li key={p.user_id} className="flex items-center gap-3">
                      <span className="w-28 shrink-0 truncate text-sm font-medium">
                        {fullName(p)}
                      </span>
                      <div className="h-5 flex-1 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${(p.count / perPersonMax) * 100}%` }}
                        />
                      </div>
                      <span className="w-8 shrink-0 text-right text-sm font-semibold tabular-nums">
                        {p.count}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </main>
  )
}
