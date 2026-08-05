import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronsUpDownIcon } from 'lucide-react'
import { timezoneNames, zoneLabel, zoneOffsetLabel } from '@/lib/timezones'
import { cn } from '@/lib/utils'
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
  value: string
  onChange: (zone: string) => void
  // Named by a visible <Label> on the household form, the same contract
  // AssigneeMultiSelect uses.
  labelledBy?: string
  id?: string
  className?: string
}

// Searchable single-select over the browser's IANA zone list, for the household form.
// Composed from Popover + Command rather than a plain Select because there are ~420 options
// and Radix's Select has no search; the shape follows AssigneeMultiSelect, down to pinning
// the popover to the trigger width.
export function TimezoneSelect({ value, onChange, labelledBy, id, className }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  // cmdk's highlighted row, controlled so it can be seeded from the stored zone. That seeding
  // is the whole point: cmdk scrolls its highlighted item into view, so opening the picker on
  // a household in Europe/Amsterdam lands on Amsterdam instead of at Africa/Abidjan with 400
  // rows to scroll. Re-seeded on every open, so reopening after an abandoned search returns to
  // the household's own zone rather than wherever the last search left the cursor.
  const [highlighted, setHighlighted] = useState(value)

  // Offsets are only computed for the rows that exist, once per open rather than per
  // keystroke: `zoneOffsetLabel` builds an Intl.DateTimeFormat each call, and 420 of those on
  // every character typed is enough to feel it.
  const zones = useMemo(
    () => timezoneNames().map((zone) => ({ zone, offset: zoneOffsetLabel(zone) })),
    [],
  )
  // The trigger's own offset, memoised for the same reason as the list: `zoneOffsetLabel` builds
  // an `Intl.DateTimeFormat` per call, and the trigger re-renders on every keystroke in the form
  // around it.
  const selectedOffset = useMemo(() => zoneOffsetLabel(value), [value])

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) setHighlighted(value)
        setOpen(next)
      }}
    >
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          aria-labelledby={labelledBy}
          className={cn(
            'flex h-10 w-full items-center justify-between gap-2 rounded-input border border-input bg-transparent px-3 py-1.5 text-left text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30',
            className,
          )}
        >
          <span className="truncate">
            {zoneLabel(value)}
            <span className="ml-2 text-muted-foreground">{selectedOffset}</span>
          </span>
          <ChevronsUpDownIcon className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0"
        align="start"
        style={{ width: 'var(--radix-popover-trigger-width)' }}
      >
        {/* Substring matching instead of cmdk's default, which scores every item by fuzzy
            subsequence and so leaves hundreds of weak matches under the right one. Fine for a
            command palette of a dozen actions; useless over 419 zone names, where typing
            "Niue" should give you Niue and nothing else. Matches the offset too, via the
            `keywords` on each item. */}
        <Command
          value={highlighted}
          onValueChange={setHighlighted}
          filter={(itemValue, search, keywords) =>
            // Named `itemValue`, not `value`: this is cmdk's per-row value and shadowing the
            // component's `value` prop here would be one rename away from a silent bug.
            [itemValue, ...(keywords ?? [])].join(' ').toLowerCase().includes(search.toLowerCase())
              ? 1
              : 0
          }
        >
          <CommandInput placeholder={t('households.timezoneSearch')} />
          <CommandList>
            <CommandEmpty>{t('households.timezoneEmpty')}</CommandEmpty>
            <CommandGroup>
              {zones.map(({ zone, offset }) => (
                <CommandItem
                  key={zone}
                  // The IANA name is the value so `onSelect` hands back exactly what the API
                  // wants; `keywords` is what the search actually matches, so typing
                  // "Amsterdam" or "GMT+2" both find the row.
                  value={zone}
                  keywords={[zoneLabel(zone), offset]}
                  data-checked={zone === value}
                  onSelect={() => {
                    onChange(zone)
                    setOpen(false)
                  }}
                >
                  {/* `flex-1` on the name and a fixed width on the offset, so the offsets form
                      a real column with their "GMT" prefixes on one vertical line.
                      Deliberately NOT `ml-auto` on the offset: CommandItem appends a CheckIcon
                      that already carries one, and two auto margins in a flex row *split* the
                      free space between them - which is what made every offset start at a
                      different x depending on how long its zone name was. `tabular-nums` stops
                      the digits shifting between rows on top of that. */}
                  <span className="flex-1 truncate">{zoneLabel(zone)}</span>
                  <span className="w-18 shrink-0 text-xs tabular-nums text-muted-foreground">
                    {offset}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
