import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronsUpDownIcon } from 'lucide-react'
import type { Tag } from '@/lib/types'
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
  tags: Tag[]
  value: number[]
  onChange: (ids: number[]) => void
  // id of the <Label> that names this control (aria-labelledby).
  labelledBy?: string
}

// Searchable multi-select for a chore's tags: the trigger summarises the chosen
// tags as coloured badges; the popover holds a search box and a checkable list
// (the list is the source of truth — click a row to add/remove). Scales to many
// tags without the long wall of pills the old ToggleGroup produced.
export function TagMultiSelect({ tags, value, onChange, labelledBy }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const selected = tags.filter((tag) => value.includes(tag.id))

  function toggle(id: number) {
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-labelledby={labelledBy}
          className="flex min-h-10 w-full items-center justify-between gap-2 rounded-input border border-input bg-transparent px-3 py-1.5 text-left text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        >
          {selected.length === 0 ? (
            <span className="text-muted-foreground">{t('choreCreate.tagsPlaceholder')}</span>
          ) : (
            <span className="flex flex-wrap items-center gap-1.5">
              {selected.map((tag) => (
                <Badge key={tag.id} variant="secondary" className="gap-1.5 font-semibold">
                  <span
                    className="inline-block size-2.5 rounded-full"
                    style={{ backgroundColor: tag.color }}
                  />
                  {tag.name}
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
          <CommandInput placeholder={t('choreCreate.tagsSearch')} />
          <CommandList>
            <CommandEmpty>{t('choreCreate.tagsEmpty')}</CommandEmpty>
            <CommandGroup>
              {tags.map((tag) => (
                <CommandItem
                  key={tag.id}
                  // Use the id (unique) as cmdk's value and the name as the
                  // search keyword: names are only case-insensitively unique to
                  // cmdk, but the DB constraint is case-sensitive, so two names
                  // differing only in case would otherwise collide.
                  value={String(tag.id)}
                  keywords={[tag.name]}
                  data-checked={value.includes(tag.id)}
                  onSelect={() => toggle(tag.id)}
                >
                  <span
                    className="inline-block size-2.5 rounded-full"
                    style={{ backgroundColor: tag.color }}
                  />
                  {tag.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
