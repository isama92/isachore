import { useState } from 'react'
import type { Editor } from '@tiptap/react'
import { useEditorState } from '@tiptap/react'
import {
  BoldIcon,
  CodeIcon,
  ItalicIcon,
  LinkIcon,
  ListIcon,
  ListOrderedIcon,
  QuoteIcon,
  StrikethroughIcon,
  UnderlineIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { isAllowedRichTextUri, RICH_TEXT_LINK_PROTOCOLS } from '@/components/rich-text/format'
import { cn } from '@/lib/utils'

// Nine buttons in one row, grouped by kind. At 28px each (icon-sm) plus gap-0.5 that is 268px,
// which fits inside the field on a 375px phone; flex-wrap is insurance for narrower still,
// not the expected layout.
//
// Every button is type="button". The editor renders inside ChoreForm's <form>, where a button
// with no type defaults to submit, so omitting it would make "bold" save the chore.

type Toggle = {
  key: 'bold' | 'italic' | 'underline' | 'strike' | 'bulletList' | 'orderedList' | 'code'
  label: 'bold' | 'italic' | 'underline' | 'strikethrough' | 'bulletList' | 'orderedList' | 'code'
  Icon: typeof BoldIcon
  run: (editor: Editor) => void
}

// Grouped as they are rendered: inline marks, then lists, then the block-ish ones. `link` and
// `blockquote` are handled separately (the first needs a URL, the second is not a mark).
const MARKS: Toggle[] = [
  { key: 'bold', label: 'bold', Icon: BoldIcon, run: (e) => e.chain().focus().toggleBold().run() },
  {
    key: 'italic',
    label: 'italic',
    Icon: ItalicIcon,
    run: (e) => e.chain().focus().toggleItalic().run(),
  },
  {
    key: 'underline',
    label: 'underline',
    Icon: UnderlineIcon,
    run: (e) => e.chain().focus().toggleUnderline().run(),
  },
  {
    key: 'strike',
    label: 'strikethrough',
    Icon: StrikethroughIcon,
    run: (e) => e.chain().focus().toggleStrike().run(),
  },
]

const LISTS: Toggle[] = [
  {
    key: 'bulletList',
    label: 'bulletList',
    Icon: ListIcon,
    run: (e) => e.chain().focus().toggleBulletList().run(),
  },
  {
    key: 'orderedList',
    label: 'orderedList',
    Icon: ListOrderedIcon,
    run: (e) => e.chain().focus().toggleOrderedList().run(),
  },
]

const BLOCKS: Toggle[] = [
  { key: 'code', label: 'code', Icon: CodeIcon, run: (e) => e.chain().focus().toggleCode().run() },
]

function Separator() {
  return <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 self-center bg-border" />
}

export default function RichTextToolbar({
  editor,
  disabled = false,
}: {
  editor: Editor
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [linkOpen, setLinkOpen] = useState(false)
  const [href, setHref] = useState('')
  // Set when setLink refuses the href; cleared on every edit and on reopening, so a stale
  // rejection cannot outlive the value that caused it.
  const [linkError, setLinkError] = useState<string | null>(null)

  // Tiptap v3's React binding does NOT re-render on transactions, so `editor.isActive(...)`
  // read straight from render would return the state the editor had at mount and never change:
  // the editor would work while the toolbar stayed dark. useEditorState is the reactive read.
  const active = useEditorState({
    editor,
    selector: ({ editor }) => ({
      bold: editor.isActive('bold'),
      italic: editor.isActive('italic'),
      underline: editor.isActive('underline'),
      strike: editor.isActive('strike'),
      bulletList: editor.isActive('bulletList'),
      orderedList: editor.isActive('orderedList'),
      code: editor.isActive('code'),
      blockquote: editor.isActive('blockquote'),
      link: editor.isActive('link'),
    }),
  })

  // Tooltip content repeats the aria-label rather than adding separate prose, matching the row
  // actions in Chores and History. The icons are the only thing on screen naming these buttons,
  // and one string keeps the sighted and screen-reader answers identical.
  function toggleButton({ key, label, Icon, run }: Toggle) {
    const name = t(`richText.${label}`)
    return (
      <Tooltip key={key}>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={disabled}
            aria-pressed={active[key]}
            aria-label={name}
            onClick={() => run(editor)}
            className={cn(active[key] && 'bg-muted text-foreground')}
          >
            <Icon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{name}</TooltipContent>
      </Tooltip>
    )
  }

  function applyLink() {
    const trimmed = href.trim()
    if (trimmed === '') return
    // A user typing "example.com" means https, and a schemeless href would otherwise resolve
    // against the app's own origin. Prefixing here is also what keeps the value inside the
    // server's ALLOWED_SCHEMES, which rejects relative URLs outright (url_relative="deny").
    //
    // The leading slashes have to go with it: "//example.com/x" and "/admin/users" are not hosts,
    // so a naive prefix produced "https:////example.com/x" - a well-formed-looking href that is
    // not what anyone typed. Stripping them turns both into a plain https URL, which the editor
    // and the server then agree on.
    const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(trimmed)
      ? trimmed
      : `https://${trimmed.replace(/^\/+/, '')}`
    // Checked here rather than by reading `run()`'s false: the chain begins with `focus()`, whose
    // effect on the DOM is not transactional, so letting it run and fail would yank the caret out
    // of this input and into the document while the error appeared beside a field the user was no
    // longer in. Same predicate the Link extension is configured with, so the two cannot disagree.
    //
    // Keeping the popover open and saying so also beats the alternative, which was closing on
    // nothing: a user types `tel:...`, presses Apply, and the popover vanishes having done
    // nothing at all. The scheme hint is already on screen, but a hint is not an answer to "I
    // just pressed the button".
    if (!isAllowedRichTextUri(withScheme)) {
      setLinkError(t('richText.linkRejected', { schemes: RICH_TEXT_LINK_PROTOCOLS.join(', ') }))
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: withScheme }).run()
    setLinkOpen(false)
  }

  function removeLink() {
    editor.chain().focus().extendMarkRange('link').unsetLink().run()
    setLinkOpen(false)
  }

  return (
    // Its own TooltipProvider, nested inside the app-wide one in RequireAuth. Radix allows the
    // nesting, and it is what makes this editor droppable anywhere - including outside RequireAuth
    // and in its own tests - without the tooltips throwing for want of a provider.
    <TooltipProvider>
      <div
        // role="group", not "toolbar": toolbar implies a single tab stop with arrow-key
        // navigation between the buttons, which would need a focus manager, and nine ordinary tab
        // stops is both honest and usable. But the role is not optional either - a bare <div>
        // computes as `generic`, which the ARIA spec prohibits naming, so the aria-label below
        // was not reliably reaching assistive tech. `group` supports a name and carries no
        // focus-management contract.
        role="group"
        data-slot="rich-text-toolbar"
        aria-label={t('richText.toolbar')}
        className="flex flex-wrap items-center gap-0.5 border-b border-input px-1.5 py-1"
      >
        {MARKS.map(toggleButton)}
        <Separator />
        {LISTS.map(toggleButton)}
        <Separator />
        {BLOCKS.map(toggleButton)}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              disabled={disabled}
              aria-pressed={active.blockquote}
              aria-label={t('richText.quote')}
              onClick={() => editor.chain().focus().toggleBlockquote().run()}
              className={cn(active.blockquote && 'bg-muted text-foreground')}
            >
              <QuoteIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('richText.quote')}</TooltipContent>
        </Tooltip>
        <Popover
          open={linkOpen}
          onOpenChange={(open) => {
            setLinkOpen(open)
            // Prefill from the selection so opening it on an existing link edits rather than
            // silently replaces. getAttributes returns {} off a link, hence the fallback.
            if (open) setHref((editor.getAttributes('link').href as string | undefined) ?? '')
            setLinkError(null)
          }}
        >
          <Tooltip>
            <TooltipTrigger asChild>
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={disabled}
                  aria-pressed={active.link}
                  aria-label={t('richText.link')}
                  className={cn(active.link && 'bg-muted text-foreground')}
                >
                  <LinkIcon />
                </Button>
              </PopoverTrigger>
            </TooltipTrigger>
            <TooltipContent>{t('richText.link')}</TooltipContent>
          </Tooltip>
          <PopoverContent className="flex w-72 flex-col gap-2">
            <Input
              value={href}
              onChange={(e) => {
                setHref(e.target.value)
                setLinkError(null)
              }}
              placeholder={t('richText.linkPlaceholder')}
              aria-label={t('richText.linkUrl')}
              aria-invalid={linkError !== null || undefined}
              // Enter inside a popover that lives inside ChoreForm's <form> would submit the
              // chore. Apply the link instead.
              onKeyDown={(e) => {
                if (e.key !== 'Enter') return
                e.preventDefault()
                applyLink()
              }}
            />
            <div className="flex items-center justify-end gap-2">
              {active.link && (
                <Button type="button" variant="ghost" size="sm" onClick={removeLink}>
                  {t('richText.linkRemove')}
                </Button>
              )}
              <Button type="button" size="sm" disabled={href.trim() === ''} onClick={applyLink}>
                {t('richText.linkApply')}
              </Button>
            </div>
            {linkError !== null ? (
              <p role="alert" className="text-[13px] font-bold text-danger">
                {linkError}
              </p>
            ) : (
              <p className="text-[13px] font-medium text-muted-foreground">
                {t('richText.linkSchemes', { schemes: RICH_TEXT_LINK_PROTOCOLS.join(', ') })}
              </p>
            )}
          </PopoverContent>
        </Popover>
      </div>
    </TooltipProvider>
  )
}
