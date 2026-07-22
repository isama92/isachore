"""two-factor auth: totp columns, challenges, recovery codes

Revision ID: 3489ad56a466
Revises: cf1c12f13d25
Create Date: 2026-07-22 05:20:39.577284

Adds TOTP two-factor auth: users.totp_secret (Fernet-encrypted seed) and
users.totp_enabled, the two_factor_challenges table (short-lived login
challenges) and two_factor_recovery_codes table (hashed single-use backup
codes), plus the 2FA audit actions.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3489ad56a466"
down_revision: str | Sequence[str] | None = "cf1c12f13d25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "two_factor_challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("remember", sa.Boolean(), nullable=False),
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
            name=op.f("fk_two_factor_challenges_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_two_factor_challenges")),
    )
    op.create_index(
        op.f("ix_two_factor_challenges_token_hash"),
        "two_factor_challenges",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "two_factor_recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_two_factor_recovery_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_two_factor_recovery_codes")),
    )
    op.create_index(
        op.f("ix_two_factor_recovery_codes_user_id"),
        "two_factor_recovery_codes",
        ["user_id"],
        unique=False,
    )

    op.add_column("users", sa.Column("totp_secret", sa.String(length=255), nullable=True))
    # server_default backfills existing rows to false, then is dropped to match
    # the model (Python-side default only).
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "totp_enabled", server_default=None)

    # New audit actions for 2FA. Postgres can't drop enum values, so there's no
    # matching downgrade for these.
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'two_factor_enabled'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'two_factor_disabled'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'two_factor_failed'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'two_factor_reset'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'two_factor_recovery_regenerated'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_index(
        op.f("ix_two_factor_recovery_codes_user_id"), table_name="two_factor_recovery_codes"
    )
    op.drop_table("two_factor_recovery_codes")
    op.drop_index(op.f("ix_two_factor_challenges_token_hash"), table_name="two_factor_challenges")
    op.drop_table("two_factor_challenges")
