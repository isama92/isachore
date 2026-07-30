import { RICH_TEXT_CLASS } from '@/components/rich-text/format'
import { cn } from '@/lib/utils'

// Renders stored rich text. The counterpart to RichTextEditor, sharing its stylesheet class so
// a description reads the way it looked while being written.
//
// This is the only place in the app that renders server data as HTML, and it does so on the
// strength of one guarantee: backend/app/core/richtext.py reduces every description to a
// twelve-tag allowlist on write, so the database cannot hold a script, an event handler, a
// style attribute or an image. That is why the sanitiser shipped before this component did.
//
// Two rules if this is ever reused:
//
// - only pass it values that went through that sanitiser. It is NOT a sanitiser itself and
//   deliberately does not pretend to be one; a second, browser-side allowlist here would be
//   defence in depth, but a *weaker* guarantee dressed up as the real one is worse than none.
// - never pass it something a user typed and the server has not seen yet. The editor's own
//   output is unsanitised by definition.
export default function RichText({
  html,
  className,
  id,
}: {
  html: string
  className?: string
  id?: string
}) {
  return (
    <div
      id={id}
      data-slot="rich-text"
      className={cn(RICH_TEXT_CLASS, className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
