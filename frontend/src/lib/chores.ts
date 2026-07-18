import i18n from '../i18n/i18n'
import { localeFor } from '../i18n/languages'
import type { AssignmentType, RepeatPeriod } from './types'

// Option values in display order. The human labels live in the translation
// files under options.repeat.* / options.assignment.*, so callers render them
// with t(`options.repeat.${value}`) rather than a static label here.
export const repeatOptions: readonly RepeatPeriod[] = [
  'manual',
  'daily',
  'weekly',
  'monthly',
  'yearly',
]

export const assignmentOptions: readonly AssignmentType[] = [
  'manual',
  'alphabetical',
  'random',
  'least_done',
]

// Today's date as a local (timezone-safe) "YYYY-MM-DD" string.
export function todayISO(): string {
  const d = new Date()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${month}-${day}`
}

// Local (timezone-safe) formatting of an ISO date-only string like "2026-07-16",
// in the active language's locale (en -> en-GB, it -> it-IT).
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  if (!year || !month || !day) return iso
  return new Date(year, month - 1, day).toLocaleDateString(localeFor(i18n.language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

// Formatting of a full ISO timestamp like "2026-07-16T14:30:00Z" as date + time
// in the active language's locale, rendered in the viewer's timezone. Used by the
// History view, where several chores can be completed on the same day.
export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(localeFor(i18n.language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
