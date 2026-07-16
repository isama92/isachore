import type { AssignmentType, RepeatPeriod } from './types'

export const repeatOptions: { value: RepeatPeriod; label: string }[] = [
  { value: 'manual', label: 'Manual' },
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

export const assignmentOptions: { value: AssignmentType; label: string }[] = [
  { value: 'manual', label: 'Manual' },
  { value: 'alphabetical', label: 'Alphabetical' },
  { value: 'random', label: 'Random' },
  { value: 'least_done', label: 'Least done' },
]

export function repeatLabel(value: RepeatPeriod): string {
  return repeatOptions.find((o) => o.value === value)?.label ?? value
}

export function assignmentLabel(value: AssignmentType): string {
  return assignmentOptions.find((o) => o.value === value)?.label ?? value
}

// Local (timezone-safe) formatting of an ISO date-only string like "2026-07-16".
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  if (!year || !month || !day) return iso
  return new Date(year, month - 1, day).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}
