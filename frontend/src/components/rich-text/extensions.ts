import StarterKit from '@tiptap/starter-kit'
import { Placeholder } from '@tiptap/extensions'
import { isAllowedRichTextUri } from '@/components/rich-text/format'

// The editor's extension set: what a user is able to produce.
//
// Separate from format.ts, which holds the constants, because this module imports StarterKit and
// format.ts is imported by the read-only renderer. Merging them would drag the whole editor into
// any bundle that only wanted to *display* rich text, defeating the code splitting in App.tsx.
//
// Configured by subtraction. Everything switched off below ships in StarterKit but sits outside
// ALLOWED_TAGS in backend/app/core/richtext.py, and the server sanitises on write, so leaving one
// on means a user formats a heading, sees it look right, saves, and gets a plain paragraph back
// with nothing explaining why.
export function richTextExtensions({ placeholder }: { placeholder?: string } = {}) {
  return [
    StarterKit.configure({
      heading: false,
      codeBlock: false,
      horizontalRule: false,
      // trailingNode keeps an empty paragraph at the end of the document so you can click below
      // the last block. It is a real node, so it serialises: left on, getHTML() ends in `<p></p>`
      // and every document looks non-empty to anything checking.
      trailingNode: false,
      // openOnClick would navigate away from a half-written chore on a stray click.
      //
      // `isAllowedUri`, NOT `protocols`: the latter only appends to Tiptap's hardcoded ten
      // schemes, so passing our three (already among them) narrows nothing and the editor would
      // accept `tel:`, `ftp:`, `sms:` and friends that the server then strips on save. See
      // isAllowedRichTextUri in format.ts, which derives the rule from the same constant the
      // server list mirrors.
      link: { openOnClick: false, isAllowedUri: isAllowedRichTextUri },
    }),
    // Unlike the extensions above, Placeholder adds no node and changes no document: it is a
    // ProseMirror decoration that sets a data-placeholder attribute and an is-editor-empty class,
    // which `.rich-text` in index.css renders as ::before content. So it cannot affect getHTML(),
    // editor.isEmpty, or what the sanitiser sees.
    //
    // Being CSS, it is also invisible to assistive tech, which is why RichTextEditor additionally
    // sets aria-placeholder on the editable.
    ...(placeholder ? [Placeholder.configure({ placeholder })] : []),
  ]
}
