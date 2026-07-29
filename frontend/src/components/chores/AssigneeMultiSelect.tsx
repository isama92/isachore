import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronsUpDownIcon, XIcon } from 'lucide-react'
import type { HouseholdMember } from '@/lib/types'
import { fullName } from '@/lib/user'
import { cn } from '@/lib/utils'
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
  // The chore form names this control with a visible <Label> (aria-labelledby);
  // the Home filter has no visible label and passes an aria-label instead.
  labelledBy?: string
  label?: string
  // Context-specific copy: the filter's placeholder means "everyone", the form's
  // means "none chosen".
  placeholder: string
  searchPlaceholder: string
  emptyText: string
  // Extra classes for the trigger (e.g. the Home filter's fixed width).
  className?: string
}

// Searchable multi-select for household members, shared by the chore form's
// assignee field and the Home assignee filter. The trigger summarises the chosen
// members as removable badges (or a placeholder when none are picked); the popover
// holds a search box, a select-all/clear action row, and a checkable list (the list
// is the source of truth — click a row to add/remove). Adapted from the chore
// form's TagMultiSelect.
export function AssigneeMultiSelect({
  members,
  value,
  onChange,
  labelledBy,
  label,
  placeholder,
  searchPlaceholder,
  emptyText,
  className,
}: Props) {
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
          aria-labelledby={labelledBy}
          aria-label={label}
          className={cn(
            'flex min-h-10 w-full items-center justify-between gap-2 rounded-input border border-input bg-transparent px-3 py-1.5 text-left text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30',
            className,
          )}
        >
          {selected.length === 0 ? (
            <span className="text-muted-foreground">{placeholder}</span>
          ) : (
            <span className="flex flex-wrap items-center gap-1.5">
              {selected.map((m) => (
                <Badge key={m.id} variant="secondary" className="gap-1 font-semibold">
                  {fullName(m)}
                  {/* A span (not a button): a button here would be interactive
                      content nested in the trigger button (invalid). stopPropagation
                      keeps the click from toggling the popover. */}
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label={t('common.remove', { name: fullName(m) })}
                    className="inline-flex items-center justify-center rounded-full text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation()
                      onChange(value.filter((v) => v !== m.id))
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        e.stopPropagation()
                        onChange(value.filter((v) => v !== m.id))
                      }
                    }}
                  >
                    <XIcon className="size-3" />
                  </span>
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
          <CommandInput placeholder={searchPlaceholder} />
          {/* Plain buttons, not CommandItems, so the search box never filters them. */}
          <div className="flex items-center justify-between border-b px-2 py-1.5">
            <button
              type="button"
              className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onChange(members.map((m) => m.id))}
            >
              {t('common.selectAll')}
            </button>
            {value.length > 0 && (
              <button
                type="button"
                className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onChange([])}
              >
                {t('common.clear')}
              </button>
            )}
          </div>
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
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
