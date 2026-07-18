import type { TFunction } from 'i18next'
import type { DueChore, DueStatus } from './types'

// Most-overdue-first. The server already sorts, but sort defensively so the UI
// (and its tests) don't depend on server order.
export function sortByDue(items: DueChore[]): DueChore[] {
  return [...items].sort((a, b) => a.days_until_due - b.days_until_due)
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
