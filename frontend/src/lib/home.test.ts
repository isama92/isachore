import { describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { dueDotClass, relativeDueLabel, sortByDue } from './home'
import { makeDueChore } from '../test/fixtures'

const t = i18n.getFixedT('en')

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
