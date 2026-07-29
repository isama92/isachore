import type { TFunction } from 'i18next'
import type { UnscheduledChore } from './types'

// An unscheduled chore has no due date, so its dot encodes recency instead of urgency:
// how long since it was last done. This is the threshold between the "recently enough"
// amber and the muted grey, matching the week that DUE_SOON_DAYS spans on the due view.
const DONE_WEEK_DAYS = 7

// Tailwind v4's JIT only sees complete class literals, so the classes are spelled out
// rather than built as `bg-done-${bucket}`, exactly as the due view's DOT map does.
// Note the tokens are --done-*, NOT --due-*: the two scales cross over (done today is
// green, whereas due today is yellow), so reusing bg-due-soon here would mislead.
export function doneDotClass(item: Pick<UnscheduledChore, 'days_since_last_completion'>): string {
  const days = item.days_since_last_completion
  if (days === null) return 'bg-done-stale'
  // `<= 0` rather than `=== 0`: a completion timestamped slightly ahead of the server's
  // clock reads as today rather than falling through to grey.
  if (days <= 0) return 'bg-done-recent'
  return days <= DONE_WEEK_DAYS ? 'bg-done-week' : 'bg-done-stale'
}

// A short, localised recency label: "Last done today" / "Last done 4 days ago" /
// "Never done". The text is what carries the meaning to a screen reader, since the dot
// beside it is aria-hidden decoration.
export function lastDoneLabel(t: TFunction, item: UnscheduledChore): string {
  const days = item.days_since_last_completion
  if (days === null) return t('unscheduled.lastDone.never')
  if (days <= 0) return t('unscheduled.lastDone.today')
  return t('unscheduled.lastDone.days', { count: days })
}
