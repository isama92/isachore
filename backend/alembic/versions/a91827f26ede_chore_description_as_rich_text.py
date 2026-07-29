"""chore description as rich text: Text column, and wrap the plain text already stored

Revision ID: a91827f26ede
Revises: 3c1f04a7e9d2
Create Date: 2026-07-29 22:19:52.063845

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a91827f26ede"
down_revision: str | Sequence[str] | None = "3c1f04a7e9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # varchar(2000) -> text is binary-coercible in Postgres, so this takes an ACCESS
    # EXCLUSIVE lock but performs no table rewrite and no scan whatever the row count.
    op.alter_column(
        "chores",
        "description",
        existing_type=sa.VARCHAR(length=2000),
        type_=sa.Text(),
        existing_nullable=True,
    )

    # NULL is now the single spelling of "no description" (see app/core/richtext.py), so
    # whitespace-only rows adopt it before anything else runs. Doing this first also keeps
    # the wrap below from producing a `<p></p>`, which the write path would have refused.
    #
    # U+00A0 is in the trim set deliberately: a paste from Word is the realistic way a
    # description ends up holding nothing but a non-breaking space, and without it such a row
    # survives as `<p>&nbsp;</p>`, which sets has_description and opens a blank dialog.
    # `is_blank` already treats it as empty, so this keeps the migration and the write path
    # agreeing on what "empty" means.
    op.execute(
        r"""
        UPDATE chores
        SET description = NULL
        WHERE description IS NOT NULL AND btrim(description, E' \t\r\n\u00A0') = ''
        """
    )

    # Every description in the database predates rich text and is plain text. The read paths
    # are about to hand it to dangerouslySetInnerHTML, which would reinterpret it: newlines
    # collapse to single spaces, and a literal `<` or `&` someone typed becomes markup or an
    # entity ("5 < 10 & rising" would render as "5 10 & rising").
    #
    # Two ordering rules, both easy to get wrong and neither caught by a test, since pytest
    # builds its schema from Base.metadata.create_all and so never executes a migration:
    #
    # - `&` is escaped FIRST. Reverse it and the `&` in the `&lt;` this step just introduced
    #   is escaped again, so a `<` arrives in the browser as the visible text "&lt;".
    # - CRLF is normalised BEFORE splitting on newlines, or a Windows-authored description
    #   leaves a stray carriage return at the end of every line.
    #
    # Each newline becomes a `<br>` inside one paragraph rather than splitting into separate
    # `<p>`s. That preserves the line structure exactly as the textarea showed it, blank runs
    # included (paragraph-splitting would collapse them), and `<p>a<br>b</p>` is also
    # precisely what Tiptap's HardBreak emits, so these rows round-trip through the editor
    # untouched instead of being silently rewritten the first time someone opens one.
    op.execute(
        r"""
        UPDATE chores
        SET description = '<p>' || replace(
                regexp_replace(
                    replace(replace(replace(description, '&', '&amp;'), '<', '&lt;'),
                            '>', '&gt;'),
                    E'\r\n?', E'\n', 'g'),
                E'\n', '<br>') || '</p>'
        WHERE description IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema.

    Lossy in three ways, all unavoidable and none of them visible at runtime, so they are
    listed rather than papered over:

    - Formatting is gone. Bold, lists and links become their text content; a plain-text
      column has nowhere to keep them.
    - Whatever the allowlist dropped on the way in was dropped for good, on write. This is
      not a round trip back to the original payload, only back to a plain-text column.
    - Content over 2000 characters is truncated to fit the varchar bound. Truncating rather
      than failing is deliberate: an operator rolling back needs the migration to finish, and
      a downgrade that aborts on one long description leaves the schema mid-change.
    """
    # Undo the upgrade's mapping first: `<br>` and the close of every block element become
    # newlines, then whatever tags remain are stripped. Closing *all* the block tags, not just
    # `</p>`, is what keeps a list from running its items together into one word; the inline
    # marks are the only ones that should vanish without leaving a boundary behind.
    #
    # The tag pattern is approximate (an attribute value holding a literal `>` would confuse
    # it), which is safe here because the allowlist permits only href and title, and nh3
    # escapes `>` inside attribute values.
    op.execute(
        r"""
        UPDATE chores
        SET description = regexp_replace(
                regexp_replace(
                    regexp_replace(description, '<br\s*/?>', E'\n', 'gi'),
                    '</(p|li|ul|ol|blockquote)\s*>', E'\n', 'gi'),
                '<[^>]*>', '', 'g')
        WHERE description IS NOT NULL
        """
    )

    # Unescape in the mirror image of the upgrade's order, so `&amp;` goes LAST. Reverse it
    # and the `&` this pass restores is consumed by the `&lt;` pass, collapsing a stored
    # "&amp;lt;" (the escaped text "&lt;") all the way down to a live `<`.
    op.execute(
        r"""
        UPDATE chores
        SET description = replace(
                replace(replace(replace(description, '&nbsp;', ' '), '&lt;', '<'),
                        '&gt;', '>'),
                '&amp;', '&')
        WHERE description IS NOT NULL
        """
    )

    # Tidy up what the two passes above left behind: a block close at the end of the fragment
    # leaves a trailing newline, and nesting (a `<p>` inside a `<blockquote>`) can leave a run
    # of them. Collapsing 3+ to 2 keeps a deliberate blank line while dropping the artefacts,
    # and it cannot touch the `<br><br>` the upgrade wrote, which is exactly 2.
    op.execute(
        r"""
        UPDATE chores
        SET description = btrim(
                regexp_replace(description, E'\n{3,}', E'\n\n', 'g'),
                E' \t\r\n\u00A0')
        WHERE description IS NOT NULL
        """
    )

    op.execute(
        r"""
        UPDATE chores
        SET description = CASE
            WHEN description = '' THEN NULL
            ELSE left(description, 2000)
        END
        WHERE description IS NOT NULL
        """
    )

    op.alter_column(
        "chores",
        "description",
        existing_type=sa.Text(),
        type_=sa.VARCHAR(length=2000),
        existing_nullable=True,
    )
