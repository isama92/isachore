import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'
import { api } from '@/lib/api'
import { buildTimeline, choreActivityTotal, SKIPPED_COLOUR } from '@/lib/choreStats'
import { endpoints } from '@/lib/endpoints'
import { formatDate } from '@/lib/chores'
import { fullName } from '@/lib/user'
import type { ChoreStatsData, StatsChoreOption, StatsRange } from '@/lib/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import { ChoreSelect } from './ChoreSelect'

type Props = {
  range: StatsRange
  // The page's filters, '' when unset: the person narrows the charts, the household the picker.
  userId: string
  householdId: string
}

// The Statistics page's per-chore section: a searchable chore picker, empty by default, and once
// a chore is picked two charts for it. First, done and skipped per person (a stacked horizontal
// bar, so the length is the turns each person dealt with and the grey tail the share they
// skipped). Second, the same chore over time, coloured by who did it, with every skip in one
// grey series on top.
export default function ChoreStatsSection({ range, userId, householdId }: Props) {
  const { t } = useTranslation()
  const [options, setOptions] = useState<StatsChoreOption[]>([])
  const [choreId, setChoreId] = useState<number | null>(null)
  // The last answer, tagged with the request it answers. Only an answer for the CURRENT request
  // is shown, so a change of chore, range or person never leaves the previous chore's charts on
  // screen while the new request is in flight, without resetting state inside the effect.
  const [result, setResult] = useState<{
    key: string
    data: ChoreStatsData | null
    error: string | null
  } | null>(null)
  const requestKey = choreId === null ? null : `${choreId}|${range}|${userId}`

  // The picker's options follow the household filter. A selection the new list no longer
  // holds is dropped rather than left charting a chore from a household that is filtered out.
  useEffect(() => {
    let cancelled = false
    const params = new URLSearchParams()
    if (householdId) params.set('household_id', householdId)
    const qs = params.toString()
    api
      .get<StatsChoreOption[]>(qs ? `${endpoints.statsChores}?${qs}` : endpoints.statsChores)
      .then((list) => {
        if (cancelled) return
        setOptions(list)
        setChoreId((id) => (id !== null && list.some((o) => o.id === id) ? id : null))
      })
      .catch(() => {
        if (cancelled) return
        // An empty picker must not sit above a chart for a chore it no longer offers.
        setOptions([])
        setChoreId(null)
      })
    return () => {
      cancelled = true
    }
  }, [householdId])

  useEffect(() => {
    if (choreId === null || requestKey === null) return
    let cancelled = false
    const params = new URLSearchParams({ range })
    if (userId) params.set('user_id', userId)
    api
      .get<ChoreStatsData>(`${endpoints.statsChore(choreId)}?${params.toString()}`)
      .then((d) => {
        if (!cancelled) setResult({ key: requestKey, data: d, error: null })
      })
      .catch(() => {
        if (!cancelled) setResult({ key: requestKey, data: null, error: t('statistics.loadError') })
      })
    return () => {
      cancelled = true
    }
  }, [choreId, range, userId, requestKey, t])

  const current = result !== null && result.key === requestKey ? result : null
  const data = current?.data ?? null
  const error = current?.error ?? null

  const showHousehold = new Set(options.map((o) => o.household_id)).size > 1

  return (
    <section className="mt-8 flex flex-col gap-4" aria-labelledby="per-chore-title">
      <h2 id="per-chore-title" className="font-display text-xl font-bold tracking-tight">
        {t('statistics.perChore.title')}
      </h2>
      <ChoreSelect
        options={options}
        value={choreId}
        onChange={setChoreId}
        showHousehold={showHousehold}
        className="sm:w-80"
      />

      {choreId === null && (
        <p className="text-sm text-muted-foreground">{t('statistics.perChore.hint')}</p>
      )}
      {error && <p className="text-[13px] font-bold text-danger">{error}</p>}
      {choreId !== null && !data && !error && <Skeleton className="h-[260px] rounded-xl" />}
      {data && <ChoreCharts data={data} />}
    </section>
  )
}

function ChoreCharts({ data }: { data: ChoreStatsData }) {
  const { t } = useTranslation()

  if (choreActivityTotal(data) === 0) {
    return (
      <Card>
        <CardContent>
          <p className="py-10 text-center text-sm text-muted-foreground">
            {t('statistics.perChore.noActivity')}
          </p>
        </CardContent>
      </Card>
    )
  }

  const peopleConfig = {
    done: { label: t('statistics.perChore.done'), color: 'var(--color-primary)' },
    skipped: { label: t('statistics.perChore.skipped'), color: SKIPPED_COLOUR },
  } satisfies ChartConfig
  const peopleRows = data.people.map((p) => ({
    name: fullName(p),
    done: p.done,
    skipped: p.skipped,
  }))

  const timeline = buildTimeline(data, {
    others: t('statistics.perChore.others'),
    skipped: t('statistics.perChore.skipped'),
  })
  const timelineConfig: ChartConfig = Object.fromEntries(
    timeline.series.map((s) => [s.key, { label: s.label, color: s.colour }]),
  )
  const formatBucket = (iso: string) => formatDate(iso)

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('statistics.perChore.people')}</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer
            config={peopleConfig}
            className="w-full"
            style={{ height: peopleRows.length * 40 + 56 }}
          >
            <BarChart data={peopleRows} layout="vertical" margin={{ left: 0, right: 8 }}>
              <CartesianGrid horizontal={false} />
              <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} width={120} />
              <ChartTooltip content={<ChartTooltipContent hideZero />} />
              <ChartLegend content={<ChartLegendContent />} />
              {/* Stacked, so the bar is every turn this person dealt with and the grey tail the
                  share they skipped. A row at zero (an assignee who never did it) stays, with no
                  bar, which is the point of always listing assignees. */}
              <Bar
                dataKey="done"
                stackId="person"
                fill="var(--color-done)"
                radius={[4, 0, 0, 4]}
                barSize={22}
                isAnimationActive={false}
              />
              <Bar
                dataKey="skipped"
                stackId="person"
                fill="var(--color-skipped)"
                radius={[0, 4, 4, 0]}
                barSize={22}
                isAnimationActive={false}
              />
            </BarChart>
          </ChartContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('statistics.perChore.timeline')}</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={timelineConfig} className="h-[240px] w-full">
            <BarChart data={timeline.rows} margin={{ left: -12, right: 8, top: 8 }}>
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
                  <ChartTooltipContent hideZero labelFormatter={(v) => formatBucket(String(v))} />
                }
              />
              {/* In stacking order (people, Others, Skipped): recharts sorts legend items by
                  data key by default, which would put "skipped" ahead of every "u<id>". */}
              <ChartLegend content={<ChartLegendContent />} itemSorter={null} />
              {timeline.series.map((s) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  stackId="timeline"
                  fill={`var(--color-${s.key})`}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          </ChartContainer>
        </CardContent>
      </Card>
    </div>
  )
}
