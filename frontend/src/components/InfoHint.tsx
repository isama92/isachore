import { useId, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { InfoIcon } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

type Props = {
  // The button's accessible name, e.g. "About taking turns". The icon alone says nothing to a
  // screen reader.
  label: string
  children: ReactNode
}

// How the popover is currently open: by a mouse resting on the icon (closes when it leaves), or
// pinned by a click, tap or key press (closes on the usual outside click / Escape).
type OpenedBy = 'hover' | 'pinned' | null

// A small "i" beside a control that explains it. A Popover rather than ui/tooltip on purpose:
// a tooltip only opens on hover or focus, which a phone has no way to do, and this app is a PWA.
// So a click or tap toggles it like any popover, and a *mouse* hovering opens it as well, so on a
// desktop it reads like a tooltip. A click while hover-opened pins it rather than closing it,
// which is what a mouse user clicking the icon they are already reading expects.
export function InfoHint({ label, children }: Props) {
  const [open, setOpen] = useState(false)
  const openedBy = useRef<OpenedBy>(null)
  const contentId = useId()

  function onPointerEnter(e: PointerEvent) {
    if (e.pointerType !== 'mouse' || open) return
    openedBy.current = 'hover'
    setOpen(true)
  }

  function onPointerLeave(e: PointerEvent) {
    if (e.pointerType !== 'mouse' || openedBy.current !== 'hover') return
    openedBy.current = null
    setOpen(false)
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        openedBy.current = next ? 'pinned' : null
        setOpen(next)
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          // Focus stays on the button (below), and Radix portals the content to the end of the
          // document, so without this a screen reader hears "expanded" and never the text.
          aria-describedby={open ? contentId : undefined}
          onPointerEnter={onPointerEnter}
          onPointerLeave={onPointerLeave}
          onClick={(e) => {
            // Radix skips its own toggle when the event is default-prevented, so this turns
            // "click while hover-opened" into "keep it open" instead of closing it under the cursor.
            if (openedBy.current === 'hover') {
              e.preventDefault()
              openedBy.current = 'pinned'
            }
          }}
          className="inline-flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <InfoIcon className="size-4" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        id={contentId}
        side="top"
        className="text-[13px] font-medium text-muted-foreground"
        // Keep focus on the icon: the content is text to read, not something to operate, and
        // moving focus into it on hover would yank the keyboard user's place.
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {children}
      </PopoverContent>
    </Popover>
  )
}
