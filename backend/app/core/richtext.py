"""The rich text format: which HTML the API accepts, and how everything else is dropped.

This module is the **single definition of the format**, and the security boundary. It runs
on write, server-side, because `/api/v1` is a JSON API with future non-browser clients: a
browser-side allowlist proves nothing, since `curl` skips it. Sanitising on write (rather
than on render) means the database never holds a payload and every consumer gets the same
clean value; the trade is that tightening the allowlist later does not retroactively clean
old rows, so a future tightening needs its own data migration.

Three things have to agree on the format and only this one is enforceable here:

- this allowlist, which decides what is *stored*.
- the Tiptap extension set in `frontend/src/components/rich-text/RichTextEditor.tsx`, which
  decides what a user can *produce*. Anything the editor can emit that is missing here is
  stripped on save, which the user experiences as their formatting silently vanishing with
  no error. `test_richtext.py` round-trips every tag below, so a Tiptap upgrade that adds a
  node to StarterKit fails a test instead of losing someone's work.
- the `.rich-text` CSS in `frontend/src/index.css`, which styles the tags on the way out.

Three denials are load-bearing, because the CSP (`docker/nginx/nginx-common.conf`) would
render what they let through rather than block it:

- no `style` attribute: `style-src` permits `'unsafe-inline'`. It is also what turns one
  paste from Google Docs into a column full of `<span style>`.
- no `img` at all: `img-src` permits `data:`, and `chores.description` is a TEXT column, so
  an allowed `<img>` would be an unbounded way to put a photo in the database.
- no scheme outside ALLOWED_SCHEMES. nh3 drops the offending attribute but keeps the
  element, so `<a href="javascript:...">` degrades to an anchor with no href.

Links get `target="_blank"` and `rel="noopener noreferrer"` forced onto them; see LINK_REL.
"""

# Stdlib, not this module: absolute imports mean `html` here is the standard library's.
# This module is deliberately NOT called `html` for exactly that reason.
from html import unescape

import nh3

# The maximum size of a rich text payload, in characters of *raw* markup, not of visible
# text. Generous on purpose: it exists to refuse a multi-megabyte paste, not to ration what
# anyone can write, so no counter is shown for it. Two coarser limits already sit in front
# (nginx's client_max_body_size and BodySizeLimitMiddleware); this is the per-field one.
MAX_RICH_TEXT_LENGTH = 20_000

# Deliberately small: paragraphs, the inline marks, both list flavours, links, inline code
# and quotes. No headings, tables or images - a chore note is a sentence and a checklist.
ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "u",
    "s",
    "ul",
    "ol",
    "li",
    "a",
    "code",
    "blockquote",
}

# What a user may set. Deliberately does NOT include `target`: that is imposed below rather
# than accepted, so nobody can author a link that navigates the app away in place.
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}

ALLOWED_SCHEMES = {"http", "https", "mailto"}

# Every link opens in a new tab, and `rel` is what makes that safe: without `noopener` the opened
# page gets a `window.opener` handle back to the app and can navigate it, and `noreferrer` keeps
# the chore's URL out of the destination's referer log.
#
# Both are FORCED here rather than merely allowed, which is the important part. nh3 rewrites the
# attributes on every anchor it emits, so a link pasted as raw HTML with `target="_self"` and no
# rel comes out with the same guarantees as one the editor made. Doing it server-side also means
# it holds for any client, not only the browser that happens to render RichText.
LINK_REL = "noopener noreferrer"
LINK_TARGET = "_blank"
FORCED_ATTRIBUTES = {"a": {"target": LINK_TARGET}}


def sanitise_html(value: str) -> str:
    """Reduce `value` to ALLOWED_TAGS, keeping the text of whatever is dropped.

    Note this does not guarantee block-wrapped output: a disallowed block tag leaves its
    text behind unwrapped (`<h1>hi</h1>` becomes `hi`). That is fine for a fragment
    rendered inside a div, and the editor cannot produce headings anyway.
    """
    return nh3.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        # ALLOWED_SCHEMES only bounds *absolute* URLs, and nh3 defaults relative ones to
        # "pass_through", so without this `//evil.example/x` and `/admin/users` survive untouched -
        # the first resolving off-site without ever passing the allowlist. Not a script vector
        # (`javascript:` and `data:` are still dropped either way), but the arrival path is exactly
        # the one this module defends: raw HTML posted by a non-browser client. Denying them also
        # matches the intent of forcing `target="_blank"`, under which an in-app relative link
        # would open the app in a second tab.
        url_relative="deny",
        link_rel=LINK_REL,
        set_tag_attribute_values=FORCED_ATTRIBUTES,
    )


def is_blank(value: str) -> bool:
    """True when `value` has no text content, however much markup it carries.

    "Empty" is not one value in HTML: every WYSIWYG emits `<p></p>`, `<p><br></p>` or
    `<p>&nbsp;</p>` for an untouched editor, and all three are truthy strings. Collapsing
    them to one predicate here is what keeps every downstream `if description:` honest.

    The unescape is not decoration. nh3 re-serialises, so stripping the tags off
    `<p>&nbsp;</p>` yields the literal seven characters `&nbsp;`, which `str.strip()` has
    nothing to do with; unescaped it becomes U+00A0, which Python does treat as whitespace.
    This is a predicate only - the unescaped form is never what gets stored, or we would be
    writing raw `<` back into a field we just sanitised.
    """
    return not unescape(nh3.clean(value, tags=set())).strip()


def sanitise_description(value: str | None) -> str | None:
    """Sanitise a rich text field, collapsing "renders as nothing" to None.

    Blankness is tested on the *cleaned* value, not the input, so a payload that is nothing
    but disallowed markup (`<script>alert(1)</script>`) stores NULL rather than an empty
    string. NULL is the single spelling of "no description" everywhere else.
    """
    if value is None:
        return None
    cleaned = sanitise_html(value)
    return None if is_blank(cleaned) else cleaned
