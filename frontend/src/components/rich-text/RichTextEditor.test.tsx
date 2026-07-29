import { useEffect, useState } from 'react'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { useEditor } from '@tiptap/react'
import RichTextEditor from './RichTextEditor'
import RichTextToolbar from './RichTextToolbar'
import type { Editor } from '@tiptap/react'
import { richTextExtensions } from '@/components/rich-text/extensions'
import { renderWithProviders } from '@/test/utils'

// Mounts the toolbar against an editor the TEST owns, so a test can drive a transaction the
// toolbar's own buttons cannot produce. RichTextToolbar already takes `editor` as a prop, so this
// needs no extra API on the component - the extension set is shared through extensions.ts, which
// is what keeps this harness honest about what the real editor can do.
function ToolbarHarness({
  content,
  onEditor,
  onUpdate,
}: {
  content: string
  onEditor: (editor: Editor) => void
  onUpdate?: () => void
}) {
  const editor = useEditor({
    extensions: richTextExtensions(),
    content,
    onUpdate: () => onUpdate?.(),
  })
  // Handed out from an effect rather than assigned during render: writing a ref mid-render is
  // what react-hooks/refs forbids, and useEditor returns null on the first pass anyway.
  useEffect(() => {
    if (editor) onEditor(editor)
  }, [editor, onEditor])
  if (!editor) return null
  return <RichTextToolbar editor={editor} />
}

// The only place in the suite that boots real Tiptap. Everywhere else (the two ChoreForm pages)
// mocks it down to a textarea, because jsdom cannot drive a contenteditable: `userEvent.type`
// dispatches key events a real ProseMirror view turns into transactions, and in jsdom the
// selection geometry those depend on does not exist.
//
// So these tests drive the editor the way the toolbar does - through commands - and assert on
// the HTML that comes out and on the toolbar's own reactivity. That covers the two things that
// can silently break: the extension set drifting from the server's allowlist, and Tiptap v3's
// non-reactive React binding leaving the toolbar dark.

function Harness({ initial = '', onChange }: { initial?: string; onChange?: (h: string) => void }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <span id="lbl">Description</span>
      <RichTextEditor
        value={value}
        labelledBy="lbl"
        onChange={(html) => {
          setValue(html)
          onChange?.(html)
        }}
      />
      <output data-testid="emitted">{value}</output>
    </>
  )
}

const emitted = () => screen.getByTestId('emitted').textContent

// Focus rather than click. A click makes ProseMirror hit-test the coordinates through
// document.elementFromPoint, which jsdom cannot answer, so it would place no selection (see the
// stub in test/setup.ts). Focusing lets ProseMirror fall back to a document-start selection,
// which is all these tests need.
async function type(text: string) {
  const user = userEvent.setup({ pointerEventsCheck: 0 })
  screen.getByRole('textbox').focus()
  await user.keyboard(text)
  return user
}

describe('RichTextEditor', () => {
  it('is labelled by the element named in labelledBy', () => {
    // A contenteditable is not a labelable element, so htmlFor/id cannot bind it. If this
    // regresses, every page test that looks the field up by its label breaks with it.
    renderWithProviders(<Harness />)
    expect(screen.getByRole('textbox')).toHaveAccessibleName('Description')
  })

  it('seeds the document from value and renders it as HTML, not text', () => {
    renderWithProviders(<Harness initial="<p>Scrub the <strong>tub</strong></p>" />)
    const box = screen.getByRole('textbox')
    expect(within(box).getByText('tub').tagName).toBe('STRONG')
  })

  it('ignores later value changes rather than fighting the caret', async () => {
    // Documented as uncontrolled. The guard matters because Tiptap normalises what it parses,
    // so a `value !== getHTML()` sync would never settle on a plain-text value and would
    // setContent on every render.
    function Rerenderer() {
      const [external, setExternal] = useState('<p>first</p>')
      return (
        <>
          <RichTextEditor value={external} onChange={() => {}} />
          <button type="button" onClick={() => setExternal('<p>second</p>')}>
            change
          </button>
        </>
      )
    }
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<Rerenderer />)
    await user.click(screen.getByRole('button', { name: 'change' }))
    expect(screen.getByRole('textbox')).toHaveTextContent('first')
  })

  it('emits an empty string, not <p></p>, for a visually empty document', async () => {
    // The whole point of the '' contract: a caller's `values.x || null` has to keep working, and
    // Tiptap holds `<p></p>` for an untouched document, which is truthy.
    const onChange = vi.fn()
    renderWithProviders(<Harness initial="<p>Scrub the tub</p>" onChange={onChange} />)
    // Select-all then delete, not Backspace: focusing puts the caret at the start of the
    // document, where Backspace is a no-op.
    await type('{Control>}a{/Control}{Backspace}')
    expect(onChange).toHaveBeenCalled()
    expect(onChange.mock.lastCall?.[0]).toBe('')
    // And the document really is empty, rather than onChange having lied about it.
    expect(screen.getByRole('textbox')).toHaveTextContent('')
  })

  it('emits HTML as the document changes', async () => {
    renderWithProviders(<Harness />)
    await type('Scrub the tub')
    expect(emitted()).toBe('<p>Scrub the tub</p>')
  })

  it('goes read-only when disabled', () => {
    // `editable` is a constructor option, so a later flip needs setEditable telling; without the
    // effect the field would stay typeable while merely looking greyed out.
    renderWithProviders(
      <>
        <span id="lbl">Description</span>
        <RichTextEditor value="<p>fixed</p>" labelledBy="lbl" disabled onChange={() => {}} />
      </>,
    )
    expect(screen.getByRole('textbox')).toHaveAttribute('contenteditable', 'false')
    for (const name of ['Bold', 'Bulleted list', 'Link']) {
      expect(screen.getByRole('button', { name })).toBeDisabled()
    }
  })

  describe('placeholder', () => {
    it('sits on the first line and is exposed to assistive tech', () => {
      // Two separate mechanisms, both needed. The visible half is a CSS ::before reading
      // data-placeholder, which Tiptap's Placeholder decoration puts on the empty first
      // paragraph; CSS content is never in the accessibility tree, so aria-placeholder on the
      // editable is what a screen reader actually gets.
      renderWithProviders(
        <>
          <span id="lbl">Description</span>
          <RichTextEditor
            value=""
            labelledBy="lbl"
            placeholder="Scrub the tub…"
            onChange={() => {}}
          />
        </>,
      )
      const box = screen.getByRole('textbox')
      expect(box).toHaveAttribute('aria-placeholder', 'Scrub the tub…')
      expect(box.querySelector('p.is-editor-empty')).toHaveAttribute(
        'data-placeholder',
        'Scrub the tub…',
      )
    })

    it('goes away once there is content', async () => {
      renderWithProviders(
        <Harness initial="" />,
        // no placeholder prop here: the class is what the CSS keys off, and it must not linger
      )
      await type('towels')
      expect(screen.getByRole('textbox').querySelector('p.is-editor-empty')).toBeNull()
    })
  })

  describe('toolbar', () => {
    it('wraps the selection in the mark', async () => {
      renderWithProviders(<Harness />)
      const user = await type('bold me')
      await user.keyboard('{Control>}a{/Control}')
      await user.click(screen.getByRole('button', { name: 'Bold' }))
      expect(emitted()).toBe('<p><strong>bold me</strong></p>')
    })

    it('tracks a selection move across a formatting boundary', async () => {
      // The test that pins useEditorState, and getting there took three attempts worth
      // recording, because the obvious versions all pass with the hook removed:
      //
      // - Tiptap v3's React binding does not re-render on transactions, so reading
      //   editor.isActive() straight from render is stale. But that staleness is invisible
      //   whenever the DOCUMENT changes, because onUpdate -> the caller's setState re-renders
      //   this component anyway and recomputes the stale read by accident. So asserting
      //   aria-pressed after an edit proves nothing.
      // - Toggling a mark at a collapsed caret looked like a pure state change, but Tiptap
      //   fires onUpdate for it too, so the caller re-renders again.
      //
      // Only moving the selection is genuinely document-free, and arrow keys cannot do it here:
      // jsdom answers caret movement with "Not implemented. The result of this interaction is
      // unreliable." Hence setTextSelection driven through ToolbarHarness, which owns the editor.
      // The everyday shape of the bug is clicking into bold text and watching the toolbar stay
      // dark. Delete useEditorState from RichTextToolbar and this test goes red; the earlier
      // versions did not.
      const onUpdate = vi.fn()
      let captured: Editor | null = null
      renderWithProviders(
        <ToolbarHarness
          content="<p><strong>bold</strong> plain</p>"
          onEditor={(e) => {
            captured = e
          }}
          onUpdate={onUpdate}
        />,
      )
      const pressed = () =>
        screen.getByRole('button', { name: 'Bold' }).getAttribute('aria-pressed')

      await waitFor(() => expect(captured).not.toBeNull())
      const editor = captured as unknown as Editor

      // Positions inside `<p><strong>bold</strong> plain</p>`: 1-5 is "bold", 5-11 is " plain".
      editor.commands.setTextSelection(3)
      await waitFor(() => expect(pressed()).toBe('true'))

      editor.commands.setTextSelection(8)
      await waitFor(() => expect(pressed()).toBe('false'))

      // Guards the premise. If this fired the document changed, and neither assertion above says
      // anything about the hook.
      expect(onUpdate).not.toHaveBeenCalled()
    })

    it('produces underline and strikethrough', async () => {
      // The frontend half of the allowlist drift guard. `<u>` and `<s>` are the two tags a
      // substring check on the server side could not distinguish from `<ul>` and `<strong>`, and
      // Underline/Strike arrive via StarterKit rather than an explicit extension, so a
      // StarterKit change could drop either. Nothing else here asserts they round-trip.
      renderWithProviders(<Harness />)
      const user = await type('note')
      await user.keyboard('{Control>}a{/Control}')

      await user.click(screen.getByRole('button', { name: 'Underline' }))
      expect(emitted()).toBe('<p><u>note</u></p>')

      await user.click(screen.getByRole('button', { name: 'Strikethrough' }))
      expect(emitted()).toBe('<p><s><u>note</u></s></p>')
    })

    it('produces both list flavours', async () => {
      renderWithProviders(<Harness />)
      const user = await type('towels')

      await user.click(screen.getByRole('button', { name: 'Bulleted list' }))
      expect(emitted()).toBe('<ul><li><p>towels</p></li></ul>')

      await user.click(screen.getByRole('button', { name: 'Numbered list' }))
      expect(emitted()).toBe('<ol><li><p>towels</p></li></ol>')
    })

    it('names each button in a tooltip as well as its aria-label', async () => {
      // The icons are the only thing naming these buttons on screen. The tooltip carries its own
      // TooltipProvider inside RichTextToolbar, so this also proves the editor works outside
      // RequireAuth (which is where the app-wide provider lives) - renderWithProviders mounts
      // neither.
      renderWithProviders(<Harness />)
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await user.hover(screen.getByRole('button', { name: 'Inline code' }))
      expect(await screen.findByRole('tooltip')).toHaveTextContent('Inline code')
    })

    it('offers exactly the nine buttons the server allowlist can hold', () => {
      // Drift guard against the toolbar, mirroring test_richtext.py's guard against the
      // sanitiser. A button added here without a matching tag in ALLOWED_TAGS is formatting a
      // user can apply and then watch disappear on save.
      renderWithProviders(<Harness />)
      const toolbar = within(screen.getByLabelText('Formatting'))
      expect(toolbar.getAllByRole('button')).toHaveLength(9)
      for (const name of [
        'Bold',
        'Italic',
        'Underline',
        'Strikethrough',
        'Bulleted list',
        'Numbered list',
        'Inline code',
        'Quote',
        'Link',
      ]) {
        expect(toolbar.getByRole('button', { name })).toBeInTheDocument()
      }
    })

    it('does not submit the surrounding form', async () => {
      // Every toolbar button needs type="button". The editor lives inside ChoreForm's <form>,
      // where a typeless button defaults to submit, so "bold" would save the chore.
      const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
      renderWithProviders(
        <form onSubmit={onSubmit}>
          <Harness />
        </form>,
      )
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      for (const name of ['Bold', 'Bulleted list', 'Quote', 'Link']) {
        await user.click(screen.getByRole('button', { name }))
      }
      expect(onSubmit).not.toHaveBeenCalled()
    })
  })

  describe('links', () => {
    it('adds a scheme to a bare host so the href survives the server allowlist', async () => {
      renderWithProviders(<Harness />)
      const user = await type('towels')
      await user.keyboard('{Control>}a{/Control}')
      await user.click(screen.getByRole('button', { name: 'Link' }))

      const pop = within(await screen.findByRole('dialog'))
      await user.type(pop.getByLabelText('Link address'), 'example.com')
      await user.click(pop.getByRole('button', { name: 'Apply' }))

      expect(emitted()).toContain('href="https://example.com"')
    })

    it('keeps a scheme the user typed', async () => {
      renderWithProviders(<Harness />)
      const user = await type('towels')
      await user.keyboard('{Control>}a{/Control}')
      await user.click(screen.getByRole('button', { name: 'Link' }))

      const pop = within(await screen.findByRole('dialog'))
      await user.type(pop.getByLabelText('Link address'), 'mailto:a@example.com')
      await user.click(pop.getByRole('button', { name: 'Apply' }))

      expect(emitted()).toContain('href="mailto:a@example.com"')
    })

    it('applies on Enter without submitting the form', async () => {
      const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
      renderWithProviders(
        <form onSubmit={onSubmit}>
          <Harness />
        </form>,
      )
      const user = await type('towels')
      await user.keyboard('{Control>}a{/Control}')
      await user.click(screen.getByRole('button', { name: 'Link' }))

      const pop = within(await screen.findByRole('dialog'))
      await user.type(pop.getByLabelText('Link address'), 'example.com{Enter}')

      expect(onSubmit).not.toHaveBeenCalled()
      expect(emitted()).toContain('href="https://example.com"')
    })
  })
})
