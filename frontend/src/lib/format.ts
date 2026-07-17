import i18n from '../i18n/i18n'
import { localeFor } from '../i18n/languages'

// Format a full ISO datetime string (e.g. "2026-01-01T00:00:00Z") in the active
// language's locale (en -> en-GB, it -> it-IT). Unlike formatDate in
// lib/chores.ts, which is for date-only strings, this parses a real timestamp.
// Returns the raw input if it can't be parsed.
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(localeFor(i18n.language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

// Full date + time, used as the title tooltip on a compact date cell.
export function formatDateTimeFull(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(localeFor(i18n.language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
