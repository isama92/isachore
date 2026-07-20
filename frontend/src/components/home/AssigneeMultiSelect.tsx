import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronsUpDownIcon } from 'lucide-react'
import type { HouseholdMember } from '@/lib/types'
import { fullName } from '@/lib/user'
import { Badge } from '@/components/ui/badge'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

type Props = {
  members: HouseholdMember[]
  value: number[]
  onChange: (ids: number[]) => void
  // Accessible name for the trigger (the filter has no visible <label>).
  label?: string
}

// Searchable multi-select for the Home assignee filter: the trigger summarises
// the chosen members as badges (or a placeholder when none are picked, meaning
// "everyone"); the popover holds a search box and a checkable list. Adapted from
// the chore form's TagMultiSelect.
export function AssigneeMultiSelect({ members, value, onChange, label }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const selected = members.filter((m) => value.includes(m.id))

  function toggle(id: number) {
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="flex min-h-10 w-full items-center justify-between gap-2 rounded-input border border-input bg-transparent px-3 py-1.5 text-left text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 sm:w-56"
        >
          {selected.length === 0 ? (
            <span className="text-muted-foreground">{t('home.filters.assigneeAll')}</span>
          ) : (
            <span className="flex flex-wrap items-center gap-1.5">
              {selected.map((m) => (
                <Badge key={m.id} variant="secondary" className="font-semibold">
                  {fullName(m)}
                </Badge>
              ))}
            </span>
          )}
          <ChevronsUpDownIcon className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0"
        align="start"
        style={{ width: 'var(--radix-popover-trigger-width)' }}
      >
        <Command>
          <CommandInput placeholder={t('home.filters.assigneeSearch')} />
          <CommandList>
            <CommandEmpty>{t('home.filters.assigneeEmpty')}</CommandEmpty>
            <CommandGroup>
              {members.map((m) => (
                <CommandItem
                  key={m.id}
                  value={String(m.id)}
                  keywords={[fullName(m)]}
                  data-checked={value.includes(m.id)}
                  onSelect={() => toggle(m.id)}
                >
                  {fullName(m)}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
