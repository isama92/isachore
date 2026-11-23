import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronsUpDownIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { StatsChoreOption } from '@/lib/types'
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
  options: StatsChoreOption[]
  // The selected chore's id, or null for none (the default: no charts until one is picked).
  value: number | null
  onChange: (id: number) => void
  // Show each option's household beside its title, for a user whose chores span several.
  showHousehold: boolean
  className?: string
}

// Searchable single-select over the chores the Statistics page can chart. Popover + Command,
// shaped like TimezoneSelect (substring filter, popover pinned to the trigger width), because a
// household can hold dozens of chores and Radix's Select has no search.
export function ChoreSelect({ options, value, onChange, showHousehold, className }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const selected = options.find((o) => o.id === value) ?? null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-label={t('statistics.perChore.label')}
          className={cn(
            'flex h-10 w-full items-center justify-between gap-2 rounded-input border border-input bg-transparent px-3 py-1.5 text-left text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30',
            className,
          )}
        >
          <span className={cn('truncate', !selected && 'text-muted-foreground')}>
            {selected ? selected.title : t('statistics.perChore.placeholder')}
            {selected && showHousehold && (
              <span className="ml-2 text-muted-foreground">{selected.household_name}</span>
            )}
          </span>
          <ChevronsUpDownIcon className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0"
        align="start"
        style={{ width: 'var(--radix-popover-trigger-width)' }}
      >
        {/* Substring matching rather than cmdk's fuzzy scoring, as in TimezoneSelect: typing
            "bin" should find "Bins", not every title that happens to contain a b, an i and an
            n in order. Only the keywords (title and household) are matched: the row's value is
            its id, and typing "3" should not find chore 3. */}
        <Command
          filter={(_itemValue, search, keywords) =>
            (keywords ?? []).join(' ').toLowerCase().includes(search.toLowerCase()) ? 1 : 0
          }
        >
          <CommandInput placeholder={t('statistics.perChore.search')} />
          <CommandList>
            <CommandEmpty>{t('statistics.perChore.noOptions')}</CommandEmpty>
            <CommandGroup>
              {options.map((o) => (
                <CommandItem
                  key={o.id}
                  // cmdk keys rows on `value`, so it must be unique: two households can hold a
                  // chore with the same title. The title is matched through `keywords`.
                  value={String(o.id)}
                  keywords={[o.title, o.household_name]}
                  data-checked={o.id === value}
                  onSelect={() => {
                    onChange(o.id)
                    setOpen(false)
                  }}
                >
                  <span className="flex-1 truncate">{o.title}</span>
                  {showHousehold && (
                    <span className="shrink-0 truncate text-xs text-muted-foreground">
                      {o.household_name}
                    </span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
