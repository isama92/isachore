import { describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { dueDotClass, relativeDueLabel, sortByDue } from './home'
import { makeDueChore } from '../test/fixtures'

const t = i18n.getFixedT('en')

describe('sortByDue', () => {
  it('orders most overdue first', () => {
    const items = [
      makeDueChore({ id: 1, days_until_due: 2 }),
      makeDueChore({ id: 2, days_until_due: -3 }),
      makeDueChore({ id: 3, days_until_due: 0 }),
    ]
    expect(sortByDue(items).map((i) => i.id)).toEqual([2, 3, 1])
  })

  it('does not mutate the input array', () => {
    const items = [
      makeDueChore({ id: 1, days_until_due: 2 }),
      makeDueChore({ id: 2, days_until_due: -1 }),
    ]
    sortByDue(items)
    expect(items.map((i) => i.id)).toEqual([1, 2])
  })
})

describe('dueDotClass', () => {
  it('maps each status to a full static class', () => {
    expect(dueDotClass('overdue')).toBe('bg-due-overdue')
    expect(dueDotClass('today')).toBe('bg-due-today')
    expect(dueDotClass('soon')).toBe('bg-due-soon')
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
