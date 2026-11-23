import { describe, expect, it } from 'vitest'
import { buildTimeline, choreActivityTotal, OTHERS_COLOUR, SKIPPED_COLOUR } from './choreStats'
import type { ChoreStatsData } from './types'

const LABELS = { others: 'Others', skipped: 'Skipped' }

function person(user_id: number, done = 0, skipped = 0) {
  return { user_id, first_name: `P${user_id}`, last_name: 'X', done, skipped }
}

// Inclusive, so the tests read as the people they describe ("1 to 10").
function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, i) => from + i)
}

function stats(overrides: Partial<ChoreStatsData> = {}): ChoreStatsData {
  return {
    chore_id: 1,
    title: 'Bins',
    range: '30d',
    granularity: 'day',
    people: [],
    over_time: [],
    ...overrides,
  }
}

describe('buildTimeline', () => {
  it('colours people by user id, not by rank, and stacks skips last', () => {
    // Sent most-active first (9 before 3), as the server does.
    const data = stats({
      people: [person(9, 5), person(3, 1)],
      over_time: [{ bucket: '2026-11-01', done: [{ user_id: 9, count: 2 }], skipped: 1 }],
    })
    const { series, rows } = buildTimeline(data, LABELS)

    expect(series).toEqual([
      { key: 'u3', label: 'P3 X', colour: 'var(--color-chart-1)' },
      { key: 'u9', label: 'P9 X', colour: 'var(--color-chart-2)' },
      { key: 'skipped', label: 'Skipped', colour: SKIPPED_COLOUR },
    ])
    expect(rows).toEqual([{ bucket: '2026-11-01', u3: 0, u9: 2, skipped: 1 }])
  })

  it('has no Others series with ten people, the tenth on the last colour', () => {
    const ids = range(1, 10)
    const { series } = buildTimeline(stats({ people: ids.map((id) => person(id)) }), LABELS)

    expect(series.map((s) => s.key)).toEqual([...ids.map((id) => `u${id}`), 'skipped'])
    expect(series[9].colour).toBe('var(--color-chart-10)')
  })

  it('folds the eleventh person onwards into one Others series, summing their counts', () => {
    const data = stats({
      people: range(1, 12).map((id) => person(id)),
      over_time: [
        {
          bucket: '2026-11-01',
          done: [
            { user_id: 1, count: 1 },
            { user_id: 11, count: 2 },
            { user_id: 12, count: 3 },
          ],
          skipped: 0,
        },
      ],
    })
    const { series, rows } = buildTimeline(data, LABELS)

    expect(series.map((s) => s.key)).toEqual([
      ...range(1, 10).map((id) => `u${id}`),
      'others',
      'skipped',
    ])
    expect(series.find((s) => s.key === 'others')).toEqual({
      key: 'others',
      label: 'Others',
      colour: OTHERS_COLOUR,
    })
    expect(rows[0]).toMatchObject({ u1: 1, others: 5, skipped: 0 })
  })
})

describe('choreActivityTotal', () => {
  it('counts completions and every skip, including one nobody is credited with', () => {
    const data = stats({
      // The person row holds no skip: it belonged to a deleted user, so only the bucket has it.
      people: [person(1, 2, 0)],
      over_time: [{ bucket: '2026-11-01', done: [], skipped: 1 }],
    })
    expect(choreActivityTotal(data)).toBe(3)
  })

  it('is zero for assignees who never touched the chore', () => {
    expect(choreActivityTotal(stats({ people: [person(1), person(2)] }))).toBe(0)
  })
})
