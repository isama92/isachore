// The rich text format, as the frontend needs to know it.
//
// The authority is backend/app/core/richtext.py: it sanitises on write, so anything disagreeing
// here is silently corrected (or silently lost) server-side. These constants exist so the
// editor's configuration and the renderer are stated once rather than in three components, and
// so a mismatch with the server is a one-line fix in a named place.
//
// Keep in step with ALLOWED_SCHEMES in backend/app/core/richtext.py.
export const RICH_TEXT_LINK_PROTOCOLS = ['http', 'https', 'mailto'] as const

// Whether a URL is one the server will keep. Built from the list above so the two cannot drift.
//
// This exists because Tiptap's `protocols` option CANNOT express it. `isAllowedUri` in
// @tiptap/extension-link starts from a hardcoded ten - http, https, ftp, ftps, mailto, tel,
// callto, sms, cid, xmpp - and `protocols` only *appends* to that list, so passing our three
// (all already in it) is a no-op. Left at the default, the editor happily accepts a `tel:` or
// `ftp:` link, renders it, and the server then drops the href on save with nothing shown to the
// user: exactly the silent formatting loss the allowlist design exists to prevent.
//
// Relative and scheme-relative URLs are rejected too, matching `url_relative="deny"` on the
// server. A relative href in a chore description has no useful meaning anyway, since every link
// is forced to `target="_blank"`.
//
// An empty string passes, mirroring Tiptap's own `!uri ||` short-circuit: it is what the editor
// sees mid-edit, and rejecting it would fight the extension rather than the input.
const ALLOWED_URI = new RegExp(`^(?:${RICH_TEXT_LINK_PROTOCOLS.join('|')}):`, 'i')

export function isAllowedRichTextUri(url: string): boolean {
  return !url || ALLOWED_URI.test(url)
}

// The class that styles rendered rich text, defined in src/index.css's @layer components.
// Shared by the editor's contenteditable and the read-only renderer, which is what makes the
// write and read views of a description match.
export const RICH_TEXT_CLASS = 'rich-text'
