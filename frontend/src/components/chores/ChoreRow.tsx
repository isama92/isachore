import { CheckIcon, FileTextIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// One chore card in a list view: a colour-coded dot + title + one line of detail, who it
// is for ("who is this for"), an optional marker for chores that carry written instructions,
// and a "Done" button. Shared by the two list pages, which
// differ only in what they put in `detail` and how they react to a completion:
//
// - Your Chores passes a due label and `exiting`, so the row plays an exit animation and
//   the rows below glide up: completing a chore either re-dates it or removes it.
// - Unscheduled Chores passes a recency label and `busy`, because the row stays put and
//   simply re-reads "Last done today" once the refetch lands.
//
// Both disable the button while their respective flag is set, so a double click cannot
// submit twice.
export default function ChoreRow({
  title,
  dotClass,
  detail,
  assignee,
  householdName,
  exiting = false,
  busy = false,
  doneText,
  doneLabel,
  descriptionLabel,
  onShowDescription,
  onComplete,
}: {
  title: string
  dotClass: string
  detail: string
  assignee: string
  // Only set when the user actually spans more than one household; undefined hides it.
  householdName?: string
  exiting?: boolean
  busy?: boolean
  doneText: string
  doneLabel: string
  // `onShowDescription` is the gate: undefined hides the icon entirely, exactly as
  // householdName above hides the household, so a chore with no instructions has no marker to
  // click and no empty dialog to reach. Callers pass the label unconditionally, which is why it
  // is only read when the handler is set - but it is the icon button's ONLY accessible name, so
  // a caller passing the handler without it ships an unnamed button.
  descriptionLabel?: string
  onShowDescription?: () => void
  onComplete: () => void
}) {
  return (
    <li
      data-exiting={exiting || undefined}
      className={cn(
        'group grid grid-rows-[1fr] mb-2 transition-[grid-template-rows,opacity,margin] duration-[420ms] ease-out last:mb-0 motion-reduce:transition-none',
        'data-[exiting]:pointer-events-none data-[exiting]:mb-0 data-[exiting]:grid-rows-[0fr] data-[exiting]:opacity-0',
      )}
    >
      <div className="overflow-hidden">
        <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-3.5 transition-transform duration-[420ms] ease-out group-data-[exiting]:-translate-x-3 group-data-[exiting]:scale-[0.97] motion-reduce:transition-none">
          <span
            className={cn('inline-block size-2.5 shrink-0 rounded-full', dotClass)}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            {/* The title and its marker share a flex row so the <p> keeps truncating: the icon
                is shrink-0 beside it rather than inline content that would be clipped with the
                text. The marker doubles as the affordance and the indicator, which is why it
                sits next to the name rather than over with the Done action. */}
            <div className="flex min-w-0 items-center gap-1.5">
              <p className="truncate font-semibold">{title}</p>
              {onShowDescription && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={descriptionLabel}
                  onClick={onShowDescription}
                  className="shrink-0 text-muted-foreground"
                >
                  <FileTextIcon />
                </Button>
              )}
            </div>
            <p className="mt-0.5 text-[13px] font-medium text-muted-foreground">{detail}</p>
            {/* On mobile the right-hand column is too cramped, so the assignee
                (and household, for multi-household users) stack here under the
                detail line. Hidden from sm up, where the right column takes over. */}
            <p className="mt-0.5 truncate text-[13px] font-medium text-muted-foreground sm:hidden">
              {assignee}
              {householdName && (
                <span className="text-muted-foreground/70"> · {householdName}</span>
              )}
            </p>
          </div>
          {/* From sm up: who this is for, and (for multi-household users) which
              household, right-aligned in its own column. */}
          <div className="hidden max-w-[9rem] shrink-0 flex-col items-end text-right sm:flex">
            <span className="w-full truncate text-[13px] font-medium text-muted-foreground">
              {assignee}
            </span>
            {householdName && (
              <span className="w-full truncate text-[11px] font-medium text-muted-foreground/70">
                {householdName}
              </span>
            )}
          </div>
          {/* Outline pill in the active accent (--primary) that fills on hover. */}
          <Button
            type="button"
            variant="ghost"
            disabled={exiting || busy}
            aria-label={doneLabel}
            onClick={onComplete}
            className="shrink-0 border-primary text-primary hover:bg-primary hover:text-primary-foreground hover:shadow-glow dark:hover:bg-primary"
          >
            <CheckIcon />
            {doneText}
          </Button>
        </div>
      </div>
    </li>
  )
}
