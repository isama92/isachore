import { useEffect } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import RichTextToolbar from '@/components/rich-text/RichTextToolbar'
import { richTextExtensions } from '@/components/rich-text/extensions'
import { RICH_TEXT_CLASS } from '@/components/rich-text/format'
import { cn } from '@/lib/utils'

// A rich text field. Field-agnostic on purpose (it knows nothing about chores) so a second field
// can reuse it; `format.ts` holds the shared constants and `extensions.ts` the editor's
// capabilities, which is where the reasoning about what is enabled lives.
//
// Emits HTML, which the backend then reduces to its allowlist on write - see
// backend/app/core/richtext.py, the single definition of the format.
//
// Deliberately UNCONTROLLED, like an <input defaultValue>: `value` seeds the document at
// mount and prop changes afterwards are ignored. The tempting sync effect
// (`if (value !== editor.getHTML()) setContent(value)`) is a trap, because Tiptap normalises
// what it parses - feed it the bare text `Replace the towels` and getHTML() returns
// `<p>Replace the towels</p>` forever, so the comparison never settles and setContent fires
// on every render, destroying the caret mid-word. Callers that need to reseed should remount
// with a `key` instead. This suits the one caller today: ChoreForm reads `initial` once at
// mount too.
export default function RichTextEditor({
  value,
  onChange,
  labelledBy,
  placeholder,
  disabled = false,
  className,
}: {
  value: string
  // Called with the document's HTML, or '' when it is visually empty. Emitting '' rather than
  // the `<p></p>` Tiptap actually holds is what keeps a caller's `values.x || null` honest:
  // "empty" is not one value in HTML, and this is the cheapest place to make it one. The
  // backend collapses it again anyway, for clients that are not this component.
  onChange: (html: string) => void
  // id of the <label> describing this field. A contenteditable is not a labelable element, so
  // htmlFor/id cannot bind it; same wiring as AssigneeMultiSelect and WeekdayPicker.
  labelledBy?: string
  placeholder?: string
  disabled?: boolean
  className?: string
}) {
  const editor = useEditor({
    extensions: richTextExtensions({ placeholder }),
    content: value,
    editable: !disabled,
    editorProps: {
      attributes: {
        // `.rich-text` is the same class the read-only renderer uses, so what you type looks
        // like what you later read. role/aria-multiline because a contenteditable div is not
        // a textbox to assistive tech unless it says so.
        // text-base on phones, overriding .rich-text's 0.875rem for the *editable* only:
        // WebKit auto-zooms the viewport when focus lands on an editable whose font-size is
        // under 16px, and this app is installed to phone home screens. The read-only renderer
        // keeps 0.875rem. Matches ui/input.tsx and ui/textarea.tsx exactly.
        class: `${RICH_TEXT_CLASS} min-h-16 w-full text-base outline-none md:text-sm`,
        role: 'textbox',
        'aria-multiline': 'true',
        ...(labelledBy ? { 'aria-labelledby': labelledBy } : {}),
        // The visible placeholder is a CSS ::before on a decoration, so it is not in the
        // accessibility tree at all. aria-placeholder is what makes it reachable, and it is the
        // right attribute rather than a described-by hint: this IS a placeholder, and it stops
        // being relevant the moment there is content.
        ...(placeholder ? { 'aria-placeholder': placeholder } : {}),
      },
    },
    onUpdate: ({ editor }) => onChange(editor.isEmpty ? '' : editor.getHTML()),
  })

  // `editable` is constructor-only, so a later `disabled` flip needs telling. Not a setState,
  // so this does not trip react-hooks' set-state-in-effect rule.
  useEffect(() => {
    editor?.setEditable(!disabled)
  }, [editor, disabled])

  if (!editor) return null

  return (
    <div
      data-slot="rich-text-editor"
      aria-disabled={disabled || undefined}
      className={cn(
        // Brand input chrome, copied from ui/textarea.tsx. Radius and min-height live here
        // rather than being passed in, because tailwind-merge cannot dedupe rounded-input
        // against a caller's rounded-*. Focus is focus-WITHIN: the ring belongs to this
        // wrapper but focus actually lands on the contenteditable inside it.
        'flex w-full flex-col rounded-input border border-input bg-transparent transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30',
        disabled && 'cursor-not-allowed bg-input/50 opacity-50 dark:bg-input/80',
        className,
      )}
    >
      <RichTextToolbar editor={editor} disabled={disabled} />
      <EditorContent editor={editor} className="px-3 py-2" />
    </div>
  )
}
