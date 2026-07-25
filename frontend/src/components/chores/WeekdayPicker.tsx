import { useTranslation } from 'react-i18next'
import { weekdayKeys } from '@/lib/chores'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

type Props = {
  // The pinned weekdays, as Monday-first indexes 0-6 (0 = Monday).
  value: number[]
  onChange: (weekdays: number[]) => void
  // id of the <Label> naming this control. A toggle row is not a labelable element,
  // so it is wired with aria-labelledby rather than htmlFor (as TagMultiSelect does).
  labelledBy?: string
}

// Which weekdays a weekly chore lands on: a row of seven pressable day toggles. An
// empty selection means "unpinned", which the caller's hint explains.
//
// Multi-select, so Radix renders the group as role="toolbar" and each item as a
// button with aria-pressed (the role="radio"/aria-checked treatment is type="single"
// only). Tests therefore query buttons and assert aria-pressed, not checkboxes.
export function WeekdayPicker({ value, onChange, labelledBy }: Props) {
  const { t } = useTranslation()

  return (
    <ToggleGroup
      type="multiple"
      variant="outline"
      aria-labelledby={labelledBy}
      // Overrides the group's base w-fit so seven days spread across the form column.
      className="w-full"
      value={value.map(String)}
      // Radix reports values in activation order, so sort here and every consumer
      // downstream (the payload, repeatLabel) reads Monday-first.
      onValueChange={(days) => onChange(days.map(Number).sort((a, b) => a - b))}
    >
      {weekdayKeys.map((key, day) => (
        <ToggleGroupItem
          key={key}
          value={String(day)}
          // The abbreviation alone is a poor accessible name, so expose the full day.
          aria-label={t(`options.weekday.${key}`)}
          // toggleVariants gives selected and hovered items the same bg-muted, so a
          // pinned day needs its own colour, including on hover.
          className="flex-1 data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:hover:bg-primary data-[state=on]:hover:text-primary-foreground"
        >
          {t(`options.weekdayShort.${key}`)}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
