import { afterEach, describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { assignmentOptions, formatDate, repeatOptions } from './chores'

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
  })
})
