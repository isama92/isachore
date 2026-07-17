import { describe, expect, it } from 'vitest'
import { formatDateTime, formatDateTimeFull } from './format'

describe('formatDateTime', () => {
  it('formats a full ISO timestamp as a localized date (no time)', () => {
    // Mid-month, midday UTC so the date can't roll into an adjacent month in
    // any test timezone. Default language is en -> en-GB locale.
    const out = formatDateTime('2026-06-15T12:00:00Z')
    expect(out).toContain('2026')
    expect(out).toMatch(/Jun/)
    expect(out).not.toMatch(/\d{1,2}:\d{2}/) // no time part
  })

  it('returns the raw input when it cannot be parsed', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
    expect(formatDateTime('')).toBe('')
  })
})

describe('formatDateTimeFull', () => {
  it('includes the date and a time part', () => {
    const out = formatDateTimeFull('2026-06-15T12:00:00Z')
    expect(out).toContain('2026')
    expect(out).toMatch(/\d{1,2}:\d{2}/) // has a time
  })

  it('returns the raw input when it cannot be parsed', () => {
    expect(formatDateTimeFull('nope')).toBe('nope')
  })
})
