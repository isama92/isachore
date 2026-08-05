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

  it("renders in the timezone it is given, not the viewer's", () => {
    // Literal expectations, not a round trip through the helper: this is a household-zone
    // case, and re-deriving the expectation with the same argument would pass even if the
    // option were dropped. 22:00Z on the 4th IS 5 August in Amsterdam - that is exactly how a
    // due slot is stored - and 11:00 on the 4th in Niue.
    expect(formatDateTime('2026-08-04T22:00:00Z', 'Europe/Amsterdam')).toBe('5 Aug 2026')
    expect(formatDateTime('2026-08-04T22:00:00Z', 'Pacific/Niue')).toBe('4 Aug 2026')
    expect(formatDateTime('2026-08-04T22:00:00Z', 'UTC')).toBe('4 Aug 2026')
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

  it('renders the time in the timezone it is given', () => {
    // The same instant, an hour and a date apart. A dropped `timeZone` option would make
    // these two identical whatever the viewer's zone is.
    const amsterdam = formatDateTimeFull('2026-08-04T22:00:00Z', 'Europe/Amsterdam')
    const utc = formatDateTimeFull('2026-08-04T22:00:00Z', 'UTC')
    expect(amsterdam).toContain('5 Aug 2026')
    expect(amsterdam).toMatch(/00:00/)
    expect(utc).toContain('4 Aug 2026')
    expect(utc).toMatch(/22:00/)
  })

  it('returns the raw input when it cannot be parsed', () => {
    expect(formatDateTimeFull('nope')).toBe('nope')
  })
})

describe('an unformattable zone', () => {
  it("degrades to the viewer's zone rather than throwing", () => {
    // The whole app is inside an ErrorBoundary, so a throw from a date cell is a reload screen.
    // These must return a formatted date, not blow up.
    expect(() => formatDateTime('2026-06-15T12:00:00Z', 'localtime')).not.toThrow()
    expect(formatDateTime('2026-06-15T12:00:00Z', 'localtime')).toMatch(/Jun/)
    expect(() => formatDateTimeFull('2026-06-15T12:00:00Z', 'Factory')).not.toThrow()
    expect(formatDateTimeFull('2026-06-15T12:00:00Z', 'Factory')).toMatch(/\d{1,2}:\d{2}/)
  })
})
