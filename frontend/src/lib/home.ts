import type { TFunction } from 'i18next'
import type { DueChore, DueStatus } from './types'

// Most-overdue-first, matching the server's (next_due, id) order so the list
// keeps a stable, predictable order (e.g. a chore that reappears at its next
// occurrence after completion lands in the right slot). The server already
// sorts; this is defensive.
export function sortByDue<T extends DueChore>(items: T[]): T[] {
  return [...items].sort(
    (a, b) => new Date(a.next_due).getTime() - new Date(b.next_due).getTime() || a.id - b.id,
  )
}

// Home lists every upcoming chore (no due-date cut-off), but chores due more than
// a week out are de-emphasised with a muted grey dot so the urgent red/amber/green
// stays reserved for what needs attention soon. This threshold is display-only.
const DUE_SOON_DAYS = 7

// Tailwind v4's JIT only sees complete class literals, so map status -> a full
// class name here rather than building `bg-due-${status}` at the call site.
const DOT: Record<DueStatus, string> = {
  overdue: 'bg-due-overdue',
  today: 'bg-due-today',
  soon: 'bg-due-soon',
}

export function dueDotClass(chore: Pick<DueChore, 'status' | 'days_until_due'>): string {
  if (chore.status === 'soon' && chore.days_until_due > DUE_SOON_DAYS) return 'bg-due-later'
  return DOT[chore.status]
}

// Home breaks its list into three sections separated by a hairline rule: what
// needs doing now, the rest of the coming week, and everything after it.
export type DueGroupKey = 'now' | 'week' | 'later'

const GROUP_ORDER: DueGroupKey[] = ['now', 'week', 'later']

// Bucketing reads days_until_due alone even though `status` exists, because the
// server derives both from the same value (`due_status` in app/core/chores.py):
// `now` is therefore exactly the overdue + today statuses. The week edge reuses
// DUE_SOON_DAYS on purpose, so the rule falls where the dot already turns grey
// rather than introducing a second, subtly different notion of "soon".
function dueGroupKey(chore: Pick<DueChore, 'days_until_due'>): DueGroupKey {
  if (chore.days_until_due <= 0) return 'now'
  return chore.days_until_due > DUE_SOON_DAYS ? 'later' : 'week'
}

// Due order, split into the sections above. Empty sections are dropped, which is
// what lets the caller put a rule before every group but the first without
// having to look ahead for the next non-empty one.
export function groupByDue<T extends DueChore>(items: T[]): { key: DueGroupKey; items: T[] }[] {
  const sorted = sortByDue(items)
  return GROUP_ORDER.map((key) => ({
    key,
    items: sorted.filter((chore) => dueGroupKey(chore) === key),
  })).filter((group) => group.items.length > 0)
}

// A short, localised due label: "3 days overdue" / "Due today" / "in 2 days".
export function relativeDueLabel(t: TFunction, item: DueChore): string {
  if (item.status === 'today') return t('home.due.today')
  const count = Math.abs(item.days_until_due)
  return item.status === 'overdue'
    ? t('home.due.overdue', { count })
    : t('home.due.soon', { count })
}
