import type { TFunction } from 'i18next'
import i18n from '../i18n/i18n'
import { localeFor } from '../i18n/languages'
import type { AssignmentType, Chore, RepeatPeriod } from './types'

// Option values in display order. The human labels live in the translation
// files under options.repeat.* / options.assignment.*, so callers render them
// with t(`options.repeat.${value}`) for the select, or repeatLabel() below for
// the full schedule as displayed in a list or on Home.
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

// Weekday translation-key suffixes in the order the backend numbers them, so the
// INDEX is the stored value: 0 = Monday .. 6 = Sunday (Python's date.weekday(), and
// the order the Monday-first Calendar renders). Deliberately not derived from JS
// Date.getDay(), which starts at Sunday. Labels live under options.weekday.* (full,
// for accessible names) and options.weekdayShort.* (abbreviated, for display).
//
// This lives here rather than beside WeekdayPicker because eslint's
// react-refresh/only-export-components rule covers src/components/** and its
// allowConstantExport escape hatch does not whitelist array expressions.
export const weekdayKeys = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

export type WeekdayKey = (typeof weekdayKeys)[number]

// Mirrors the backend's core.chores.MAX_INTERVAL. Bounding it here too keeps a large
// value from coming back as a pydantic 422, whose `detail` is a list rather than a string,
// so the api wrapper cannot translate it and the form would show the browser's own
// "Unprocessable Content". The form's `max` attribute is what actually stops a submit; the
// clamp on the way out is belt and braces for a value arriving some other way.
export const MAX_REPEAT_INTERVAL = 365

// A chore's schedule as one localised string: "Weekly", "Weekly (Tue, Fri)",
// "Every 2 days", "Every 2 weeks (Tue)". Takes `t` rather than reading the i18n
// singleton (the same shape as relativeDueLabel in lib/home.ts), so it uses the
// caller's render-time translator and re-renders on a language change.
export function repeatLabel(
  t: TFunction,
  chore: Pick<Chore, 'repeats' | 'repeat_interval' | 'weekdays'>,
): string {
  // A one-off never recurs, so neither the interval nor the weekdays apply. Returning
  // here also narrows `repeats` to the four periods the keys below exist for.
  if (chore.repeats === 'manual') return t('options.repeat.manual')

  const interval = Math.max(1, Math.trunc(chore.repeat_interval) || 1)
  const schedule = t(`options.repeatEvery.${chore.repeats}`, { count: interval })
  if (chore.repeats !== 'weekly') return schedule

  // Sorted Monday-first and range-checked: the picker reports days in click order, and
  // a hand-edited row could hold anything.
  const days = (chore.weekdays ?? [])
    .filter((day) => Number.isInteger(day) && day >= 0 && day < weekdayKeys.length)
    .sort((a, b) => a - b)
    .map((day) => t(`options.weekdayShort.${weekdayKeys[day]}`))
  if (days.length === 0) return schedule

  // Joined with a plain ", ": Intl.ListFormat cannot produce a comma list in Italian at
  // any style ('unit' still injects " e ", 'narrow' drops the separators entirely).
  return t('options.repeatOnDays', { schedule, days: days.join(', ') })
}

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
