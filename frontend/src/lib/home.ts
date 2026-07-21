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

// A short, localised due label: "3 days overdue" / "Due today" / "in 2 days".
export function relativeDueLabel(t: TFunction, item: DueChore): string {
  if (item.status === 'today') return t('home.due.today')
  const count = Math.abs(item.days_until_due)
  return item.status === 'overdue'
    ? t('home.due.overdue', { count })
    : t('home.due.soon', { count })
}
