from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OidcLoginState(Base):
    """One in-flight single sign-on attempt, from the redirect out to the callback back.

    Mirrors TwoFactorChallenge: only the SHA-256 hash of the token is stored, the raw
    value rides in the httpOnly isachore_oidc cookie, and it is deleted the moment it
    is used. Unlike that table there is no user_id, because at this point nobody has
    identified themselves yet - which is also why nothing cascades into it and it needs
    its own sweep (purge_expired_oidc_states).

    A table rather than stuffing all three values into the cookie, for three reasons
    that a cookie cannot cover:

    - `nonce` and `code_verifier` are what prove the callback belongs to the flow we
      started. Client-held copies could be swapped for an attacker's own, which is
      exactly what PKCE and the nonce exist to prevent.
    - Deleting the row on use makes a flow single-use, so a captured callback url
      cannot be replayed.
    - `expires_at` bounds it, like every other short-lived token here.

    The raw token doubles as the OAuth2 `state` parameter, so the callback can require
    the query parameter and the cookie to match. That is the browser binding: without
    it, an attacker could start their own flow and feed the victim its callback url,
    landing the victim in the attacker's session.
    """

    __tablename__ = "oidc_login_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    # Where to send the browser after a successful sign-in, as a site-relative path.
    # The login page's router state cannot survive a full-page navigation to the
    # provider, so the return target makes the round trip here instead. Validated as
    # relative before it is stored, so this can never become an open redirect.
    return_to: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
