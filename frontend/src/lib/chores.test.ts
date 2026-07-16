import { describe, expect, it } from 'vitest'
import { assignmentLabel, formatDate, repeatLabel } from './chores'

describe('chore helpers', () => {
  it('formats an ISO date to a UK-style short date', () => {
    expect(formatDate('2026-07-16')).toBe('16 Jul 2026')
  })

  it('falls back to the raw string for a malformed date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })

  it('labels repeat periods and assignment types', () => {
    expect(repeatLabel('manual')).toBe('Manual')
    expect(repeatLabel('weekly')).toBe('Weekly')
    expect(assignmentLabel('least_done')).toBe('Least done')
  })
})
