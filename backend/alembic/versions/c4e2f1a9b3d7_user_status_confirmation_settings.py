"""user status, confirmation tokens and app settings

Revision ID: c4e2f1a9b3d7
Revises: 7c55585588af
Create Date: 2026-07-17 00:00:00.000000

Replaces users.is_active with a status lifecycle (waiting_confirmation / active
/ disabled) plus a confirmed_at timestamp, and adds the confirmation_tokens and
app_settings tables backing the email-confirmation feature.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e2f1a9b3d7"
down_revision: str | Sequence[str] | None = "7c55585588af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # users: is_active -> status + confirmed_at. server_default backfills any
    # existing rows to 'active', then is dropped to match the model (Python-side
    # default only).
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
    )
    op.alter_column("users", "status", server_default=None)
    op.add_column("users", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("users", "is_active")

    op.create_table(
        "confirmation_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_confirmation_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confirmation_tokens")),
    )
    op.create_index(
        op.f("ix_confirmation_tokens_token_hash"),
        "confirmation_tokens",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("require_confirmation", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_settings")),
    )
    # Seed the single settings row (get_app_settings also creates it on demand).
    op.execute("INSERT INTO app_settings (id, require_confirmation) VALUES (1, false)")

    # New audit action for account confirmation. Enum values can't be dropped in
    # Postgres, so there's no matching downgrade.
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user_confirmed'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_confirmation_tokens_token_hash"), table_name="confirmation_tokens")
    op.drop_table("confirmation_tokens")
    op.drop_table("app_settings")

    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("users", "is_active", server_default=None)
    op.drop_column("users", "confirmed_at")
    op.drop_column("users", "status")
