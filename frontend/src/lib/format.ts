import i18n from '../i18n/i18n'
import { localeFor } from '../i18n/languages'

// Format a full ISO datetime string (e.g. "2026-01-01T00:00:00Z") in the active
// language's locale (en -> en-GB, it -> it-IT). Unlike formatDate in
// lib/chores.ts, which is for date-only strings, this parses a real timestamp.
// Returns the raw input if it can't be parsed.
//
// `timeZone` is the IANA zone to render in, and household-scoped surfaces MUST pass the
// household's: a due slot is stored as local midnight there, so in any other zone it prints
// the adjacent day and contradicts the server-computed "Due today" beside it. Omitted, it
// falls back to the viewer's own zone, which is right for account and admin timestamps
// (a user's created_at, an invitation's expiry) - those belong to no household.
export function formatDateTime(iso: string, timeZone?: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(localeFor(i18n.language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone,
  })
}

// Full date + time, used as the title tooltip on a compact date cell. See formatDateTime
// for when to pass `timeZone`.
export function formatDateTimeFull(iso: string, timeZone?: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(localeFor(i18n.language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone,
  })
}
