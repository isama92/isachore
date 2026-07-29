"""Pure coverage of the HTML allowlist (app.core.richtext).

Split from test_chores.py on the same principle as test_chores_core.py: the exhaustive
format cases belong to the functions, and test_chores.py keeps only enough to prove the
validator is actually wired into POST and PATCH rather than merely importable.
"""

import re

from app.core.richtext import (
    ALLOWED_TAGS,
    MAX_RICH_TEXT_LENGTH,
    is_blank,
    sanitise_description,
    sanitise_html,
)

# One fragment exercising every tag in ALLOWED_TAGS, and the attributes allowed on `a`.
EVERY_ALLOWED_TAG = (
    "<p><strong>b</strong><em>i</em><u>u</u><s>s</s><code>c</code><br></p>"
    "<ul><li>bullet</li></ul>"
    "<ol><li>numbered</li></ol>"
    "<blockquote><p>quoted</p></blockquote>"
    '<p><a href="https://example.com" title="t">link</a></p>'
)


def test_every_allowed_tag_survives() -> None:
    """The drift guard. If a Tiptap upgrade lets the editor emit something this allowlist
    strips, a user watches their formatting vanish on save with no error; if the allowlist
    grows past what the editor can produce, we are carrying surface for nothing. Either way
    the fix starts here, so this asserts tag-by-tag rather than on the whole string."""
    cleaned = sanitise_html(EVERY_ALLOWED_TAG)
    for tag in ALLOWED_TAGS:
        # The boundary is load-bearing. A bare `f"<{tag}"` substring check is satisfied for `u`
        # by `<ul>` and for `s` by `<strong>`, so two of the twelve tags were unpinned and could
        # be deleted from ALLOWED_TAGS with this test still green - the exact fall-through the
        # docstring above claims to prevent.
        assert re.search(rf"<{tag}[ >]", cleaned), tag
    assert 'href="https://example.com"' in cleaned
    assert 'title="t"' in cleaned


def test_link_gets_rel_and_keeps_allowed_schemes() -> None:
    for scheme in ("http://a.test", "https://a.test", "mailto:a@example.com"):
        cleaned = sanitise_html(f'<a href="{scheme}">x</a>')
        assert f'href="{scheme}"' in cleaned, scheme
        assert 'rel="noopener noreferrer"' in cleaned, scheme


def test_every_link_is_forced_to_open_in_a_new_tab() -> None:
    """target and rel are imposed, not accepted, so the guarantee does not depend on the editor
    having produced them. Without `noopener` the opened page gets a window.opener handle back to
    the app and can navigate it, which is why this is not merely cosmetic."""
    # A link with neither attribute gains both.
    assert sanitise_html('<a href="https://a.test">x</a>') == (
        '<a href="https://a.test" target="_blank" rel="noopener noreferrer">x</a>'
    )
    # And one that tried to opt out is overridden rather than left alone. This is the case that
    # makes the difference between forcing and allowing: a payload posted straight to the API with
    # `target="_self"` and no rel would otherwise keep both.
    assert sanitise_html('<a href="https://a.test" target="_self" rel="opener">x</a>') == (
        '<a href="https://a.test" target="_blank" rel="noopener noreferrer">x</a>'
    )


def test_strips_scripts_handlers_styles_and_images() -> None:
    # Each case pairs an input with the exact expected output, so a change in *how* nh3
    # drops something is visible rather than passing on a vague "no script here" assertion.
    cases = [
        # A script's content goes with it, not just its tags.
        ("<p>hi<script>alert(1)</script></p>", "<p>hi</p>"),
        # Event handlers on an otherwise allowed tag.
        ('<p onclick="steal()">hi</p>', "<p>hi</p>"),
        ('<strong onmouseover="x">b</strong>', "<strong>b</strong>"),
        # style attributes: the CSP permits 'unsafe-inline' for styles, so these must not
        # reach the browser.
        ('<p style="position:fixed;inset:0">hi</p>', "<p>hi</p>"),
        # Images entirely: img-src permits data:, and description is a TEXT column.
        ('<p>a</p><img src="data:image/png;base64,AAA">', "<p>a</p>"),
        ('<img src="x" onerror="alert(1)">', ""),
        # Disallowed tags keep their text but lose their markup.
        ("<h1>Heading</h1>", "Heading"),
        ("<table><tr><td>cell</td></tr></table>", "cell"),
        ('<iframe src="https://evil.test"></iframe>', ""),
    ]
    for raw, expected in cases:
        assert sanitise_html(raw) == expected, raw


def test_drops_disallowed_url_schemes_but_keeps_the_element() -> None:
    # nh3 removes the offending attribute rather than the anchor, so a poisoned link
    # degrades to unclickable text instead of disappearing mid-sentence.
    for scheme in ("javascript:alert(1)", "data:text/html,<script>x</script>", "vbscript:x"):
        cleaned = sanitise_html(f'<a href="{scheme}">click</a>')
        assert "href" not in cleaned, scheme
        assert ">click</a>" in cleaned, scheme


def test_escaped_entities_are_preserved_not_re_interpreted() -> None:
    # A description reading "5 < 10 & rising" must round-trip as text, not become markup.
    assert sanitise_html("<p>5 &lt; 10 &amp; rising</p>") == "<p>5 &lt; 10 &amp; rising</p>"


def test_malformed_markup_is_closed_rather_than_rejected() -> None:
    assert sanitise_html("<p>unclosed <strong>bold") == "<p>unclosed <strong>bold</strong></p>"
    assert sanitise_html("<ul><li>a<li>b</ul>") == "<ul><li>a</li><li>b</li></ul>"


def test_is_blank_covers_every_spelling_of_empty() -> None:
    # "Empty" is not one value in HTML. Every WYSIWYG emits one of these for an untouched
    # editor and all of them are truthy strings, which is what makes a bare `if description`
    # wrong. The &nbsp; case is the one that needs the unescape in is_blank: nh3 re-escapes
    # on the way out, so stripping tags leaves the literal seven characters "&nbsp;".
    for blank in ("", "<p></p>", "<p><br></p>", "<p>&nbsp;</p>", "<p> </p>", "<p><em></em></p>"):
        assert is_blank(blank) is True, blank
    for filled in ("hi", "<p>hi</p>", "<p><strong>hi</strong></p>", "<ul><li>hi</li></ul>"):
        assert is_blank(filled) is False, filled


def test_sanitise_description_collapses_blank_to_none() -> None:
    assert sanitise_description(None) is None
    for blank in ("", "<p></p>", "<p><br></p>", "<p>&nbsp;</p>"):
        assert sanitise_description(blank) is None, blank
    # Blankness is tested on the *cleaned* value, so a payload made only of disallowed
    # markup stores NULL rather than an empty string.
    assert sanitise_description("<script>alert(1)</script>") is None
    assert sanitise_description('<img src="x">') is None
    assert sanitise_description("<p>real</p>") == "<p>real</p>"


def test_sanitise_description_does_not_unescape_what_it_stores() -> None:
    """is_blank unescapes to make its decision; that must not leak into the stored value,
    or we would write raw `<` back into a field we just sanitised."""
    assert sanitise_description("<p>&lt;script&gt;</p>") == "<p>&lt;script&gt;</p>"


def test_plain_text_passes_through_unchanged() -> None:
    # Every description in the database predates rich text, and the migration wraps them,
    # but a plain-text client is still valid input.
    assert sanitise_description("Replace the towels") == "Replace the towels"


def test_max_length_is_measured_in_markup_not_visible_text() -> None:
    """The cap is documented as a raw-markup limit, which is only meaningful if markup can
    actually exhaust it. Enforcement lives in the schema; this pins the constant's meaning."""
    mostly_markup = "<strong>x</strong>" * 2_000
    assert len(mostly_markup) > MAX_RICH_TEXT_LENGTH
    assert len(sanitise_html(mostly_markup)) > MAX_RICH_TEXT_LENGTH
