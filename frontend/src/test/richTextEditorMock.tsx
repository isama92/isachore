// Stand-in for RichTextEditor, for tests about a FORM that happens to contain one.
//
// This is the only vi.mock in the suite, and it exists because jsdom cannot drive a
// contenteditable. ProseMirror turns key events into transactions using selection geometry that
// jsdom does not implement: caret movement answers "Not implemented. The result of this
// interaction is unreliable.", and a click needs document.elementFromPoint, which does not exist.
// The real editor is exercised for real in RichTextEditor.test.tsx, which works around all of
// that by driving commands instead of keys.
//
// So page tests get a plain textarea with the same contract: same accessible name (via
// labelledBy, since a contenteditable is not labelable), value in, string out. That keeps
// getByLabelText('Description') and toHaveValue(...) working, which is what the ChoreCreate and
// ChoreEdit suites already assert, and keeps those tests about the form rather than the editor.
//
// What it deliberately does NOT reproduce: the '' -for-empty normalisation, and the fact that
// real output is HTML. A test that cares about either belongs in RichTextEditor.test.tsx.
export default function MockRichTextEditor({
  value,
  onChange,
  labelledBy,
  placeholder,
  disabled,
}: {
  value: string
  onChange: (html: string) => void
  labelledBy?: string
  placeholder?: string
  disabled?: boolean
}) {
  return (
    <textarea
      data-slot="rich-text-editor"
      aria-labelledby={labelledBy}
      placeholder={placeholder}
      disabled={disabled}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}
