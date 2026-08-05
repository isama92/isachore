// IANA timezone names for the household picker, plus the labels it shows.
//
// The list comes from the browser (`Intl.supportedValuesOf`), not from a bundled table:
// keeping ~420 zone names in the app would be dead weight that goes stale, and the browser's
// list is already the one its own formatting accepts. The backend validates against Python's
// tz database on write, so a name the two disagree about is a 422 rather than a bad row.

import i18n from '../i18n/i18n'
import { localeFor } from '../i18n/languages'

// The floor when `Intl.supportedValuesOf` is missing (it needs Chrome 99 / Firefox 93 /
// Safari 15.4). Deliberately tiny and not a curated world list: it exists so the form still
// submits something valid rather than to be a usable picker, and anyone on a browser that old
// can still be given a zone by an admin. UTC is first so it is the visible default.
const FALLBACK_ZONES = [
  'UTC',
  'Europe/Amsterdam',
  'Europe/London',
  'America/New_York',
  'America/Los_Angeles',
  'Asia/Tokyo',
  'Australia/Sydney',
]

// Resolved once: `supportedValuesOf` builds a fresh ~420-entry array on every call, and the
// picker would otherwise rebuild it on each keystroke.
let cached: string[] | null = null

export function timezoneNames(): string[] {
  if (cached) return cached
  // `supportedValuesOf` is missing on older browsers and `Intl` itself can be absent under
  // some test environments, so this is feature-detected rather than assumed.
  const supported = Intl.supportedValuesOf?.('timeZone')
  const zones = supported && supported.length > 0 ? [...supported] : [...FALLBACK_ZONES]
  // Sorted here rather than trusted from the source: `supportedValuesOf` does return them
  // alphabetically, but that is the spec's business and the fallback list is hand-written, so
  // the picker states the order it wants instead of inheriting one.
  zones.sort((a, b) => a.localeCompare(b))
  // `supportedValuesOf` returns *canonical* zone names, and plain "UTC" is not among them -
  // it lists 418 city zones and no `Etc/*` at all. It has to be added by hand, because it is
  // a real stored value: it is the households.timezone column's server_default, and Python's
  // `available_timezones()` (which the backend validates against) does include it. Without
  // this a household on UTC renders in the trigger but cannot be found in the list, so an
  // owner who picked anything else could never get back.
  //
  // Pinned to the top rather than sorted in among the "U"s, which is the one deliberate break
  // in the ordering: it is the neutral choice and the column's default, so it should be the
  // first thing offered rather than something to scroll 400 rows for.
  cached = zones.includes('UTC') ? zones : ['UTC', ...zones]
  return cached
}

// The viewer's own zone, used to prefill the create form. Falls back to UTC rather than
// guessing: a wrong zone here is the bug this feature fixes, and the field is visible and
// editable, so an obviously-neutral default is better than a plausible wrong one.
export function browserTimezone(): string {
  const detected = Intl.DateTimeFormat().resolvedOptions().timeZone
  return detected && timezoneNames().includes(detected) ? detected : 'UTC'
}

// Zones already checked against `Intl`, so a formatter called per table row pays the probe once
// rather than per render. Bounded by the number of distinct zones a session actually sees.
const renderable = new Map<string, boolean>()

// `timeZone` if the browser can format with it, else undefined - which is what `Intl` options
// take to mean "the viewer's own zone".
//
// Load-bearing rather than defensive. Python's `available_timezones()` is a *superset* of
// `Intl.supportedValuesOf('timeZone')`: 599 names against 418 here, and two of the extras
// (`localtime`, `Factory`) throw `RangeError` in every browser. The backend now refuses those on
// write, but a household stored one before that, or a zone newer than this browser's tz database,
// reaches the same place - and an uncaught throw inside a cell renderer hits `main.tsx`'s
// ErrorBoundary and replaces the whole app with the reload screen, including the Households page
// that could set the value back. Degrading to the viewer's zone is what the app did before
// household zones existed, so it is the right floor.
export function renderableZone(timeZone?: string): string | undefined {
  if (!timeZone) return undefined
  let ok = renderable.get(timeZone)
  if (ok === undefined) {
    try {
      new Intl.DateTimeFormat('en-GB', { timeZone })
      ok = true
    } catch {
      ok = false
    }
    renderable.set(timeZone, ok)
  }
  return ok ? timeZone : undefined
}

// The current UTC offset of a zone, as the browser writes it ("GMT+2", "GMT-11:30").
// Recomputed rather than cached because it changes with DST, and a picker showing a
// half-year-old offset would be actively misleading.
export function zoneOffsetLabel(zone: string): string {
  try {
    const parts = new Intl.DateTimeFormat(localeFor(i18n.language), {
      timeZone: zone,
      timeZoneName: 'shortOffset',
    }).formatToParts(new Date())
    return parts.find((p) => p.type === 'timeZoneName')?.value ?? ''
  } catch {
    // An unknown zone reaches here only if the browser's list and its formatter disagree.
    // A missing offset degrades the label; throwing would take out the whole form.
    return ''
  }
}

// "Europe/Amsterdam" -> "Europe / Amsterdam". The underscores in IANA names are an encoding
// artefact ("New_York"), not something to show a user.
export function zoneLabel(zone: string): string {
  return zone.replace(/_/g, ' ').replace(/\//g, ' / ')
}
