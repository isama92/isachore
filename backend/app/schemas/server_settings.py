from pydantic import BaseModel


class ServerSettingsRead(BaseModel):
    require_confirmation: bool
    # Whether SMTP is configured in the environment (derived, not stored). The
    # admin UI uses it to disable the test-email button and warn that
    # confirmation can't be enabled without it.
    smtp_configured: bool
    # The configured mail-server address + port + From address, surfaced
    # read-only on the admin page. The username/password are never exposed.
    smtp_host: str | None = None
    smtp_port: int
    smtp_from: str | None = None
    # Single sign-on, reported exactly like SMTP above: a derived "is it usable"
    # boolean plus the non-secret values, read-only from the environment. The client
    # secret is never exposed, for the same reason smtp_password is not.
    #
    # Flat oidc_* fields rather than a nested object, to match the smtp_* group. The
    # redirect uri is the operationally useful one: it is derived rather than
    # configured, so an operator otherwise has to reconstruct it by hand to register
    # it with the provider.
    oidc_configured: bool
    oidc_provider_name: str
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_redirect_uri: str
    # Whether password sign-in has been switched off in favour of the provider.
    oidc_only: bool


class ServerSettingsUpdate(BaseModel):
    require_confirmation: bool
