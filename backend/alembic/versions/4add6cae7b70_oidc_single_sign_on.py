"""oidc single sign-on

Revision ID: 4add6cae7b70
Revises: e4b6c09d15af
Create Date: 2026-08-05 14:54:11.905501

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4add6cae7b70"
down_revision: str | Sequence[str] | None = "e4b6c09d15af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # One in-flight sign-on attempt per row, from the redirect out to the callback back.
    # No user_id, deliberately: at this point nobody has identified themselves yet,
    # which is also why nothing cascades into this table and it carries a sweep of its
    # own (purge_expired_oidc_states in app/core/tokens.py).
    #
    # Same hash-at-rest shape as auth_tokens, confirmation_tokens and
    # two_factor_challenges: the raw token lives in an httpOnly cookie and doubles as
    # the OAuth2 `state` parameter, so only its SHA-256 is stored here. `state_hash` is
    # unique and indexed because it is the only way a row is ever looked up, on the hot
    # path of every sign-in.
    op.create_table(
        "oidc_login_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("return_to", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_login_states")),
    )
    op.create_index(
        op.f("ix_oidc_login_states_state_hash"),
        "oidc_login_states",
        ["state_hash"],
        unique=True,
    )

    # The link between a local account and an external identity, written on a first SSO
    # sign-in. Nullable with no backfill and no default, because NULL is the honest
    # value for every existing row: none of them has ever used a provider. A linked
    # account keeps its password, so this adds a way in rather than replacing one. Both
    # are metadata-only ADD COLUMNs.
    op.add_column("users", sa.Column("oidc_subject", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("oidc_issuer", sa.String(length=255), nullable=True))

    # One local account per external identity, across the PAIR rather than the subject
    # alone: `sub` is only promised to be unique per issuer, so keying on it alone would
    # mean repointing OIDC_ISSUER at a different provider with colliding subject values
    # could match one person onto another's account. Safe to add to a populated table
    # because Postgres treats NULLs as distinct, so every not-yet-linked account is
    # exempt however many there are.
    op.create_unique_constraint("uq_users_oidc_identity", "users", ["oidc_issuer", "oidc_subject"])


def downgrade() -> None:
    """Downgrade schema."""
    # Dropping the columns unlinks every account from its external identity, so after a
    # downgrade and upgrade round trip the next SSO sign-in re-links by email exactly as
    # a first one does. Data loss in the strict sense, but not a loss of access, which
    # is why there is nothing here worth preserving. Any in-flight sign-on dies with the
    # table: the browser gets one refusal and a retry works.
    op.drop_constraint("uq_users_oidc_identity", "users", type_="unique")
    op.drop_column("users", "oidc_issuer")
    op.drop_column("users", "oidc_subject")
    op.drop_index(op.f("ix_oidc_login_states_state_hash"), table_name="oidc_login_states")
    op.drop_table("oidc_login_states")
