"""personal access tokens

Revision ID: 85c9542f74ba
Revises: 4add6cae7b70
Create Date: 2026-09-16 09:41:07.312884

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85c9542f74ba"
down_revision: str | Sequence[str] | None = "4add6cae7b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # One long-lived credential per account, for a client with no browser. The same
    # hash-at-rest shape as auth_tokens and confirmation_tokens, minus the expiry: this
    # one never lapses, so nothing sweeps it and revoking means deleting the row.
    #
    # The UNIQUE on user_id is the feature, not a tidiness measure. "At most one per
    # account" is enforced here rather than by a read before the insert, so two requests
    # racing cannot both mint one and the second gets the 409 from the constraint.
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_api_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("user_id", name=op.f("uq_api_tokens_user_id")),
    )
    op.create_index(op.f("ix_api_tokens_token_hash"), "api_tokens", ["token_hash"], unique=True)

    # audit_events.action is a native enum, so the two new members cost this. Autogenerate
    # never produces it, and NOTHING in CI catches its absence: pytest builds the type from
    # Base.metadata.create_all with every member present, `alembic check` does not diff enum
    # members at all, and the empty-database job inserts no audit row. A forgotten ALTER TYPE
    # therefore ships green and fails in production the first time somebody creates a token.
    #
    # Legal inside alembic's transaction since PostgreSQL 12; the surviving restriction is
    # that a new value cannot be USED in the same transaction, and nothing here uses one.
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'api_token_created'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'api_token_revoked'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_api_tokens_token_hash"), table_name="api_tokens")
    op.drop_table("api_tokens")
    # The two audit_action members stay, and this is the honest end of it rather than an
    # oversight. PostgreSQL has no ALTER TYPE ... DROP VALUE, so the only way back is to
    # build a replacement type and rewrite audit_events with a USING cast - which takes an
    # ACCESS EXCLUSIVE lock on the trail and then fails outright on any row already holding
    # one of the two, meaning it breaks on exactly the deployments that used the feature.
    # Deleting audit rows to make a downgrade succeed is not a trade an append-only trail
    # can make. Leaving them is inert: with the table and the endpoints gone, nothing writes
    # either value, and re-running the upgrade is a no-op thanks to IF NOT EXISTS above.
