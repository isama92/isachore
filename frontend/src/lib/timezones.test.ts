import { afterEach, describe, expect, it, vi } from 'vitest'
import { browserTimezone, timezoneNames, zoneLabel, zoneOffsetLabel } from './timezones'

describe('timezoneNames', () => {
  it('offers the browser list, including the zones the app cares about', () => {
    const zones = timezoneNames()
    expect(zones).toContain('UTC')
    expect(zones).toContain('Europe/Amsterdam')
    // Comfortably more than the fallback list, i.e. this really is the browser's set. A
    // failure here means `Intl.supportedValuesOf` is missing and every user is being offered
    // seven zones.
    expect(zones.length).toBeGreaterThan(100)
  })

  it('is alphabetical, with UTC pinned first', () => {
    const zones = timezoneNames()
    // UTC is the deliberate exception: the neutral choice and the column default, so it is
    // offered first rather than buried among the "U"s 400 rows down.
    expect(zones[0]).toBe('UTC')
    const rest = zones.slice(1)
    expect(rest).toEqual([...rest].sort((a, b) => a.localeCompare(b)))
  })
})

describe('browserTimezone', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reports a detected zone that the picker can actually offer', () => {
    const detected = browserTimezone()
    expect(timezoneNames()).toContain(detected)
  })

  it('falls back to UTC when the browser names a zone the list does not have', () => {
    // The failure mode worth guarding: a detected value the picker cannot show would leave
    // the trigger blank and submit something the backend rejects. UTC is the neutral floor -
    // deliberately not a plausible-looking guess, since a wrong zone is the bug being fixed.
    vi.spyOn(Intl, 'DateTimeFormat').mockReturnValue({
      resolvedOptions: () => ({ timeZone: 'Mars/Olympus_Mons' }),
    } as unknown as Intl.DateTimeFormat)
    expect(browserTimezone()).toBe('UTC')
  })
})

describe('zoneLabel', () => {
  it('expands the IANA encoding rather than showing it raw', () => {
    expect(zoneLabel('America/New_York')).toBe('America / New York')
    expect(zoneLabel('America/Argentina/Buenos_Aires')).toBe('America / Argentina / Buenos Aires')
    expect(zoneLabel('UTC')).toBe('UTC')
  })
})

describe('zoneOffsetLabel', () => {
  it('reports the offset the browser would format with', () => {
    expect(zoneOffsetLabel('UTC')).toMatch(/^GMT/)
    // Amsterdam is +1 or +2 depending on the date, so the sign is the assertion and the
    // number deliberately is not: pinning "GMT+2" would fail for half the year.
    expect(zoneOffsetLabel('Europe/Amsterdam')).toMatch(/^GMT\+[12]$/)
    expect(zoneOffsetLabel('Pacific/Niue')).toBe('GMT-11')
  })

  it('degrades to an empty label rather than throwing on an unknown zone', () => {
    // Only reachable if the browser's own list and its formatter disagree. A throw here would
    // take out the whole household form, which is a far worse outcome than a missing offset.
    expect(zoneOffsetLabel('Mars/Olympus_Mons')).toBe('')
  })
})
