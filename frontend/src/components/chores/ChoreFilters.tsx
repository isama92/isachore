import { useTranslation } from 'react-i18next'
import { AssigneeMultiSelect } from '@/components/chores/AssigneeMultiSelect'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { HistoryFilterOptions } from '@/lib/types'
import { cn } from '@/lib/utils'

// Radix Selects can't hold an empty value, so the "all" option uses a sentinel that maps
// back to an omitted filter (same pattern as History and Statistics).
const ALL = 'all'

// The household + assignee filter bar shared by the two chore list pages. Each control
// appears only when there is something to choose between, and the bar renders nothing at
// all for a lone user in a lone household: two selects with one option each would be pure
// noise.
//
// `group` picks up the calling page's copy. Both carry the same filter strings under their
// own key, matching how History and Statistics each carry their own rather than sharing.
export default function ChoreFilters({
  group,
  options,
  householdId,
  onHouseholdChange,
  assigneeIds,
  onAssigneeChange,
  className,
}: {
  group: 'home' | 'unscheduled'
  options: HistoryFilterOptions
  householdId: string
  onHouseholdChange: (id: string) => void
  assigneeIds: number[]
  onAssigneeChange: (ids: number[]) => void
  className?: string
}) {
  const { t } = useTranslation()
  const showHouseholds = options.households.length > 1
  const showMembers = options.members.length > 1
  if (!showHouseholds && !showMembers) return null

  return (
    <div className={cn('flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center', className)}>
      {showHouseholds && (
        <Select
          value={householdId || ALL}
          onValueChange={(v) => onHouseholdChange(v === ALL ? '' : v)}
        >
          <SelectTrigger className="sm:w-56" aria-label={t(`${group}.filters.householdLabel`)}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t(`${group}.filters.householdAll`)}</SelectItem>
            {options.households.map((h) => (
              <SelectItem key={h.id} value={String(h.id)}>
                {h.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {showMembers && (
        <AssigneeMultiSelect
          members={options.members}
          value={assigneeIds}
          onChange={onAssigneeChange}
          label={t(`${group}.filters.assigneeLabel`)}
          placeholder={t(`${group}.filters.assigneeAll`)}
          searchPlaceholder={t(`${group}.filters.assigneeSearch`)}
          emptyText={t(`${group}.filters.assigneeEmpty`)}
          className="sm:w-56"
        />
      )}
    </div>
  )
}
