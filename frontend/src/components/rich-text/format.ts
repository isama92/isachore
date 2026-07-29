// The rich text format, as the frontend needs to know it.
//
// The authority is backend/app/core/richtext.py: it sanitises on write, so anything disagreeing
// here is silently corrected (or silently lost) server-side. These constants exist so the
// editor's configuration and the renderer are stated once rather than in three components, and
// so a mismatch with the server is a one-line fix in a named place.
//
// Keep in step with ALLOWED_SCHEMES in backend/app/core/richtext.py.
export const RICH_TEXT_LINK_PROTOCOLS = ['http', 'https', 'mailto'] as const

// The class that styles rendered rich text, defined in src/index.css's @layer components.
// Shared by the editor's contenteditable and the read-only renderer, which is what makes the
// write and read views of a description match.
export const RICH_TEXT_CLASS = 'rich-text'
