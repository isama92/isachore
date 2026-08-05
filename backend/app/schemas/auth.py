from pydantic import BaseModel


class AuthMethodsRead(BaseModel):
    """Which ways in the login page should offer. Public and unauthenticated, because
    the page that needs it is the one nobody has signed in to yet.

    Safe to expose: it carries no secret and nothing account-specific, only what a
    visitor is about to be shown anyway. The admin-only /settings payload reports the
    same provider from an operator's angle (issuer, client id, the redirect uri to
    register), which is why this one stays deliberately minimal - a public endpoint is
    the wrong place to grow configuration detail.
    """

    # False only under OIDC_ONLY with a usable provider, which is also exactly when
    # POST /auth/login answers 403. The two read the same condition, so the form is
    # never hidden while the endpoint works, nor offered while it refuses.
    password_enabled: bool
    oidc_enabled: bool
    # Whatever OIDC_PROVIDER_NAME says, for the "Sign in with ..." label. Null when
    # there is no provider, so a client cannot render a button for nothing.
    oidc_provider_name: str | None = None
