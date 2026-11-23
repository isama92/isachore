import { fullName } from './user'
import type { ChoreStatsData } from './types'

// How many people get a colour of their own on the per-chore timeline: the reserved categorical
// ramp (--chart-1..10 in index.css) has ten. Everyone after that shares one "Others" series
// rather than a generated eleventh hue, which could no longer be told apart from its neighbours.
export const TIMELINE_COLOURS = 10
// Spelled out in full, never built as `var(--color-chart-${n})`: Tailwind v4 only emits a
// `--color-*` theme variable whose name it finds written in the source, so a computed name
// resolves to nothing and the bar renders black. (Only the ones some other file happened to
// spell out used to survive, which is how this hid at first.)
const CHART_COLOURS = [
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
  'var(--color-chart-5)',
  'var(--color-chart-6)',
  'var(--color-chart-7)',
  'var(--color-chart-8)',
  'var(--color-chart-9)',
  'var(--color-chart-10)',
] as const satisfies readonly string[] & { length: typeof TIMELINE_COLOURS }
// The "Others" fill. A grey, so it never reads as one more person, but NOT --stat-skipped:
// skips are stacked in the same bars and the two must stay apart. --muted-foreground is the
// heavier grey of the same family (see the --stat-skipped comment in index.css).
export const OTHERS_COLOUR = 'var(--color-muted-foreground)'
export const SKIPPED_COLOUR = 'var(--color-stat-skipped)'

export type TimelineSeries = { key: string; label: string; colour: string }

// The per-chore timeline's series and rows, kept out of the component so the colour and
// "Others" rules can be tested without a rendered chart (recharts draws nothing in jsdom).
//
// A colour per person, in user-id order among the people in the answer, so it follows the
// person rather than their rank: whoever did the most this month does not repaint the chart.
// Series come back in stacking order: people, then Others, then the skips on top, as on the
// page's other stacked chart.
export function buildTimeline(
  data: ChoreStatsData,
  labels: { others: string; skipped: string },
): { series: TimelineSeries[]; rows: Record<string, string | number>[] } {
  const byId = [...data.people].sort((a, b) => a.user_id - b.user_id)
  const keyOf = new Map<number, string>()
  const series: TimelineSeries[] = []
  byId.forEach((p, i) => {
    if (i < TIMELINE_COLOURS) {
      keyOf.set(p.user_id, `u${p.user_id}`)
      series.push({
        key: `u${p.user_id}`,
        label: fullName(p),
        colour: CHART_COLOURS[i],
      })
    } else {
      keyOf.set(p.user_id, 'others')
    }
  })
  if (byId.length > TIMELINE_COLOURS) {
    series.push({ key: 'others', label: labels.others, colour: OTHERS_COLOUR })
  }
  series.push({ key: 'skipped', label: labels.skipped, colour: SKIPPED_COLOUR })

  const rows = data.over_time.map((b) => {
    const row: Record<string, string | number> = { bucket: b.bucket }
    for (const s of series) row[s.key] = 0
    row.skipped = b.skipped
    for (const d of b.done) {
      // A completer missing from `people` cannot happen (the server lists everyone with a
      // closure), but folding them into Others beats dropping their count if it ever does.
      const key = keyOf.get(d.user_id) ?? 'others'
      row[key] = Number(row[key] ?? 0) + d.count
    }
    return row
  })
  return { series, rows }
}

// Everything the chore saw in the range, skips included. Skips are summed from the buckets
// rather than the people: a skip whose completer was deleted is in nobody's row but is still a
// skip. Known gap: a COMPLETION by a deleted user is in neither the people nor the buckets
// (the server drops it with its completer), so a range holding only that reads as empty.
export function choreActivityTotal(data: ChoreStatsData): number {
  return (
    data.people.reduce((sum, p) => sum + p.done, 0) +
    data.over_time.reduce((sum, b) => sum + b.skipped, 0)
  )
}
