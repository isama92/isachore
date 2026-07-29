import { describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { dueDotClass, groupByDue, relativeDueLabel, sortByDue } from './home'
import { makeDueChore } from '../test/fixtures'
import type { DueChore } from './types'

const t = i18n.getFixedT('en')

const TODAY = Date.parse('2026-07-18T09:00:00Z')
const DAY_MS = 86_400_000

// A chore whose next_due agrees with its days_until_due, so the sort inside
// groupByDue orders by the same thing the sections are cut on. The status is
// filled in the way the server would, which is what makes "now == overdue +
// today" visible in the fixtures rather than only in the assertions.
function dueIn(id: number, days: number): DueChore {
  return makeDueChore({
    id,
    days_until_due: days,
    next_due: new Date(TODAY + days * DAY_MS).toISOString(),
    status: days < 0 ? 'overdue' : days === 0 ? 'today' : 'soon',
  })
}

describe('sortByDue', () => {
  it('orders most overdue first (earliest next_due)', () => {
    const items = [
      makeDueChore({ id: 1, next_due: '2026-07-20T09:00:00Z', days_until_due: 2 }),
      makeDueChore({ id: 2, next_due: '2026-07-15T09:00:00Z', days_until_due: -3 }),
      makeDueChore({ id: 3, next_due: '2026-07-18T09:00:00Z', days_until_due: 0 }),
    ]
    expect(sortByDue(items).map((i) => i.id)).toEqual([2, 3, 1])
  })

  it('breaks same-instant ties by id, ordering within a day by time', () => {
    const items = [
      makeDueChore({ id: 2, next_due: '2026-07-18T14:30:00Z', days_until_due: 0 }),
      makeDueChore({ id: 1, next_due: '2026-07-18T09:00:00Z', days_until_due: 0 }),
      makeDueChore({ id: 3, next_due: '2026-07-18T09:00:00Z', days_until_due: 0 }),
    ]
    expect(sortByDue(items).map((i) => i.id)).toEqual([1, 3, 2])
  })

  it('does not mutate the input array', () => {
    const items = [
      makeDueChore({ id: 1, next_due: '2026-07-20T09:00:00Z' }),
      makeDueChore({ id: 2, next_due: '2026-07-15T09:00:00Z' }),
    ]
    sortByDue(items)
    expect(items.map((i) => i.id)).toEqual([1, 2])
  })
})

describe('dueDotClass', () => {
  it('maps each status to a full static class', () => {
    expect(dueDotClass(makeDueChore({ status: 'overdue', days_until_due: -3 }))).toBe(
      'bg-due-overdue',
    )
    expect(dueDotClass(makeDueChore({ status: 'today', days_until_due: 0 }))).toBe('bg-due-today')
    expect(dueDotClass(makeDueChore({ status: 'soon', days_until_due: 2 }))).toBe('bg-due-soon')
  })

  it('greys the dot for chores due more than a week out', () => {
    // Day 7 is still "soon" green; day 8 and beyond are de-emphasised grey.
    expect(dueDotClass(makeDueChore({ status: 'soon', days_until_due: 7 }))).toBe('bg-due-soon')
    expect(dueDotClass(makeDueChore({ status: 'soon', days_until_due: 8 }))).toBe('bg-due-later')
    expect(dueDotClass(makeDueChore({ status: 'soon', days_until_due: 30 }))).toBe('bg-due-later')
  })
})

describe('groupByDue', () => {
  it('breaks between today and tomorrow, keeping overdue with today', () => {
    const groups = groupByDue([dueIn(1, -2), dueIn(2, 0), dueIn(3, 1)])
    expect(groups.map((g) => g.key)).toEqual(['now', 'week'])
    expect(groups[0].items.map((c) => c.id)).toEqual([1, 2])
    expect(groups[1].items.map((c) => c.id)).toEqual([3])
  })

  it('breaks at the week edge, where the dot turns grey', () => {
    // Deliberately the same 7/8 pair as the dueDotClass test above: the rule and
    // the grey dot read one threshold, so moving it has to break both.
    const groups = groupByDue([dueIn(1, 7), dueIn(2, 8)])
    expect(groups.map((g) => g.key)).toEqual(['week', 'later'])
    expect(groups[0].items.map((c) => c.id)).toEqual([1])
    expect(groups[1].items.map((c) => c.id)).toEqual([2])
  })

  it('drops empty sections', () => {
    expect(groupByDue([dueIn(1, 3), dueIn(2, 5)]).map((g) => g.key)).toEqual(['week'])
    expect(groupByDue([])).toEqual([])
    // Non-contiguous: something overdue plus a monthly chore, nothing this week.
    expect(groupByDue([dueIn(1, -1), dueIn(2, 20)]).map((g) => g.key)).toEqual(['now', 'later'])
  })

  it('orders the sections, and sorts by due date within each', () => {
    const groups = groupByDue([dueIn(5, 30), dueIn(2, 0), dueIn(3, 5), dueIn(1, -3), dueIn(4, 12)])
    expect(groups.map((g) => g.key)).toEqual(['now', 'week', 'later'])
    expect(groups.map((g) => g.items.map((c) => c.id))).toEqual([[1, 2], [3], [4, 5]])
  })
})

describe('relativeDueLabel', () => {
  it('labels overdue with singular/plural days', () => {
    expect(relativeDueLabel(t, makeDueChore({ status: 'overdue', days_until_due: -3 }))).toBe(
      '3 days overdue',
    )
    expect(relativeDueLabel(t, makeDueChore({ status: 'overdue', days_until_due: -1 }))).toBe(
      '1 day overdue',
    )
  })

  it('labels due-today without a count', () => {
    expect(relativeDueLabel(t, makeDueChore({ status: 'today', days_until_due: 0 }))).toBe(
      'Due today',
    )
  })

  it('labels soon with singular/plural days', () => {
    expect(relativeDueLabel(t, makeDueChore({ status: 'soon', days_until_due: 2 }))).toBe(
      'in 2 days',
    )
    expect(relativeDueLabel(t, makeDueChore({ status: 'soon', days_until_due: 1 }))).toBe(
      'in 1 day',
    )
  })
})
