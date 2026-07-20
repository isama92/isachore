import type { TFunction } from 'i18next'
import type { DueChore, DueStatus } from './types'

// Most-overdue-first, matching the server's (next_due, id) order so the list
// keeps a stable, predictable order (e.g. a chore that reappears at its next
// occurrence after completion lands in the right slot). The server already
// sorts; this is defensive.
export function sortByDue(items: DueChore[]): DueChore[] {
  return [...items].sort(
    (a, b) => new Date(a.next_due).getTime() - new Date(b.next_due).getTime() || a.id - b.id,
  )
}

// Tailwind v4's JIT only sees complete class literals, so map status -> a full
// class name here rather than building `bg-due-${status}` at the call site.
const DOT: Record<DueStatus, string> = {
  overdue: 'bg-due-overdue',
  today: 'bg-due-today',
  soon: 'bg-due-soon',
}

export function dueDotClass(status: DueStatus): string {
  return DOT[status]
}

// A short, localised due label: "3 days overdue" / "Due today" / "in 2 days".
export function relativeDueLabel(t: TFunction, item: DueChore): string {
  if (item.status === 'today') return t('home.due.today')
  const count = Math.abs(item.days_until_due)
  return item.status === 'overdue'
    ? t('home.due.overdue', { count })
    : t('home.due.soon', { count })
}
