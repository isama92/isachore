import { afterEach, describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { assignmentOptions, formatDate, repeatLabel, repeatOptions, weekdayKeys } from './chores'
import type { Chore, RepeatPeriod } from './types'

// Just the fields repeatLabel reads, so a case reads as the schedule it describes.
function schedule(
  repeats: RepeatPeriod,
  repeat_interval = 1,
  weekdays: number[] | null = null,
): Pick<Chore, 'repeats' | 'repeat_interval' | 'weekdays'> {
  return { repeats, repeat_interval, weekdays }
}

describe('chore helpers', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('formats an ISO date to a UK-style short date in English', () => {
    expect(formatDate('2026-07-16')).toBe('16 Jul 2026')
  })

  it('falls back to the raw string for a malformed date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })

  it('formats the date in the active language locale', async () => {
    await i18n.changeLanguage('it')
    const expected = new Date(2026, 6, 16).toLocaleDateString('it-IT', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
    expect(formatDate('2026-07-16')).toBe(expected)
    // it-IT ("16 lug 2026") must differ from the en-GB default, proving the
    // formatter follows the language rather than a hardcoded locale.
    expect(formatDate('2026-07-16')).not.toBe('16 Jul 2026')
  })

  it('exposes the option values in display order', () => {
    expect(repeatOptions).toEqual(['manual', 'daily', 'weekly', 'monthly', 'yearly'])
    expect(assignmentOptions).toEqual(['manual', 'alphabetical', 'random', 'least_done'])
    // The index IS the stored weekday, so this order pins 0 = Monday.
    expect(weekdayKeys).toEqual(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])
  })
})

describe('repeatLabel', () => {
  // A fixed translator, so the language-switch case above cannot leak into these.
  const t = i18n.getFixedT('en')

  it('reads as the bare period at an interval of one', () => {
    expect(repeatLabel(t, schedule('weekly'))).toBe('Weekly')
    expect(repeatLabel(t, schedule('daily'))).toBe('Daily')
    expect(repeatLabel(t, schedule('monthly'))).toBe('Monthly')
    expect(repeatLabel(t, schedule('yearly'))).toBe('Yearly')
  })

  it('spells out an interval above one', () => {
    expect(repeatLabel(t, schedule('daily', 3))).toBe('Every 3 days')
    expect(repeatLabel(t, schedule('weekly', 2))).toBe('Every 2 weeks')
    expect(repeatLabel(t, schedule('monthly', 2))).toBe('Every 2 months')
    expect(repeatLabel(t, schedule('yearly', 2))).toBe('Every 2 years')
  })

  it('appends the pinned weekdays for a weekly chore', () => {
    expect(repeatLabel(t, schedule('weekly', 1, [1, 4]))).toBe('Weekly (Tue, Fri)')
    expect(repeatLabel(t, schedule('weekly', 2, [1]))).toBe('Every 2 weeks (Tue)')
  })

  it('sorts the weekdays Monday-first whatever order they arrive in', () => {
    // The picker reports days in click order, so [4, 1] is a value the API can return.
    expect(repeatLabel(t, schedule('weekly', 1, [4, 1]))).toBe('Weekly (Tue, Fri)')
  })

  it('ignores weekdays on a period that cannot be pinned', () => {
    expect(repeatLabel(t, schedule('daily', 1, [1, 4]))).toBe('Daily')
    expect(repeatLabel(t, schedule('monthly', 2, [1]))).toBe('Every 2 months')
  })

  it('treats null and an empty list alike, as unpinned', () => {
    expect(repeatLabel(t, schedule('weekly', 1, null))).toBe('Weekly')
    expect(repeatLabel(t, schedule('weekly', 1, []))).toBe('Weekly')
  })

  it('never applies an interval or weekdays to a one-off', () => {
    expect(repeatLabel(t, schedule('manual'))).toBe('Manual')
    expect(repeatLabel(t, schedule('manual', 3, [1]))).toBe('Manual')
  })

  it('drops an out-of-range weekday rather than rendering a missing key', () => {
    expect(repeatLabel(t, schedule('weekly', 1, [9]))).toBe('Weekly')
    expect(repeatLabel(t, schedule('weekly', 1, [1, 9]))).toBe('Weekly (Tue)')
  })

  it('floors a nonsensical interval to one', () => {
    expect(repeatLabel(t, schedule('weekly', 0))).toBe('Weekly')
  })

  it('renders in the active language', () => {
    const it_ = i18n.getFixedT('it')
    expect(repeatLabel(it_, schedule('daily', 2))).toBe('Ogni 2 giorni')
    expect(repeatLabel(it_, schedule('weekly', 1, [1, 4]))).toBe('Ogni settimana (mar, ven)')
    // Proving the label follows the language rather than a hardcoded locale.
    expect(repeatLabel(it_, schedule('weekly', 1, [1, 4]))).not.toBe(
      repeatLabel(t, schedule('weekly', 1, [1, 4])),
    )
  })
})
