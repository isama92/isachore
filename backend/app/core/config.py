from pydantic_settings import BaseSettings, SettingsConfigDict

# Environment markers that count as "a developer's machine". Anything else reads
# as a real deployment, which is fail-safe: an unset ENVIRONMENT defaults to
# "prod" and a typo like "prood" lands on the strict side. Two things gate on
# this: the destructive `python -m app.cli seed` (refuses to run outside it) and
# the prod boot check in app/core/startup.py (I1, only runs outside it).
DEV_ENVIRONMENTS = frozenset({"dev", "development", "local", "test", "testing"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Deployment marker (e.g. "dev" / "prod"). Cookie security is controlled by
    # cookies_secure below, not by this value. Defaults to "prod" so an
    # unconfigured deploy fails safe: it gates the dev-only `seed` command and
    # the startup config check (see DEV_ENVIRONMENTS above), so dev and test opt
    # out explicitly (dev compose reads it from .env).
    environment: str = "prod"

    # Auth cookies get the Secure flag (HTTPS only) by default, so a deploy that
    # configures nothing fails closed. Local dev is served over plain HTTP, so
    # it must opt out explicitly with COOKIES_SECURE=false.
    cookies_secure: bool = True

    # Symmetric key for encrypting secrets at rest (a urlsafe-base64 Fernet key;
    # generate with `python -m app.cli generate-key`). General-purpose, consumed
    # via app/core/crypto.py; the first user is 2FA (the TOTP seed must be
    # recoverable, so it is encrypted rather than hashed). Optional in a dev
    # environment, where anything needing encryption fails closed while it is
    # unset; REQUIRED outside one, where a missing or malformed key refuses boot
    # (I1, app/core/startup.py) rather than silently locking out every enrolled
    # 2FA user. Rotating this key strands data encrypted under the old one unless
    # key rotation is added later.
    app_key: str | None = None

    # Default targets localhost for host-side tooling; docker compose overrides
    # the host to "db" via env_file. The +asyncpg scheme is required.
    database_url: str = (
        "postgresql+asyncpg://isachore:isachore_dev_password@localhost:5432/isachore"
    )

    # Redis backs login rate limiting (M2). Default targets localhost for
    # host-side tooling; docker compose overrides the host to "redis".
    redis_url: str = "redis://localhost:6379/0"

    # Login throttling: after this many failed attempts within the window, /login
    # returns 429 until the window elapses. Counted per attempted email and (more
    # loosely) per client IP; the IP limit is higher to tolerate shared NATs.
    login_max_attempts: int = 5
    login_ip_max_attempts: int = 20
    login_attempt_window: int = 900  # seconds (15 minutes)

    # Two-factor code verification throttle. A 6-digit TOTP has a tiny space, so
    # the verify step is brute-forceable if unbounded: after this many failed
    # codes for one user within login_attempt_window, /auth/verify-2fa returns
    # 429. Tighter than the login limit; the per-IP dimension reuses
    # login_ip_max_attempts. Fails open on a Redis outage, like the login
    # throttle.
    two_factor_max_attempts: int = 5
    # Issuer label shown next to the account in authenticator apps (the QR /
    # otpauth URI). Cosmetic; changing it does not invalidate existing enrolments.
    totp_issuer: str = "isachore"

    # Cooldown between admin "send test email" clicks, per admin. Stops the
    # button from hammering the SMTP relay / an admin's inbox; enforced in Redis
    # (best-effort, fails open) and mirrored by a countdown in the admin UI. Keep
    # in sync with TEST_EMAIL_COOLDOWN_SECONDS in the frontend ServerSettings page.
    test_email_cooldown: int = 10  # seconds

    # Trust the client IP from the X-Forwarded-For header. Off by default (safe
    # for direct/dev access); turn on only behind a trusted reverse proxy such as
    # the prod nginx, which sets the header.
    trust_forwarded_for: bool = False

    # Where uploaded files live, relative to the backend working dir (/app in the
    # container). Avatars go under <storage_dir>/avatars. Backed by a host bind
    # mount in dev and a named volume in prod so they survive restarts.
    storage_dir: str = "storage"
    # Upper bound on the raw uploaded bytes, checked before decoding (bounds the
    # compressed upload). ~5 MB. The Profile page mirrors this default in
    # AVATAR_MAX_MB to reject an oversized pick without uploading it and to word
    # its size hint, so lowering this here alone leaves the UI advertising 5 MB;
    # move both together. Nothing breaks if they disagree (the server still
    # rejects, and its 413 message deliberately quotes no figure), the hint just
    # becomes a lie.
    avatar_max_bytes: int = 5 * 1024 * 1024
    # Upper bound on the decoded pixel count, checked from the image header
    # before allocating the bitmap (bounds memory / decompression bombs). 50 MP
    # comfortably covers real phone photos.
    avatar_max_pixels: int = 50_000_000
    # Side length (px) of the square avatar we re-encode and store.
    avatar_px: int = 512
    # Upper bound on any request body, enforced at the ASGI layer (413 past it)
    # by BodySizeLimitMiddleware. Defence in depth behind the prod nginx
    # client_max_body_size (keep the two in sync): without it, a directly
    # exposed backend would spool arbitrarily large multipart bodies before any
    # handler-level check runs. Must stay above avatar_max_bytes plus multipart
    # overhead. ~6 MB.
    max_request_bytes: int = 6 * 1024 * 1024

    # Public base URL of the SPA, used to build the confirmation link emailed to
    # a new user (<app_base_url>/confirm?token=...). Dev default is the Vite
    # server; prod must set it to the real origin.
    app_base_url: str = "http://localhost:5173"

    # SMTP for account-confirmation and test emails. All optional so the app
    # boots without email configured; "require confirmation" and the test-email
    # button are gated on smtp_configured() (host + from address). In dev,
    # compose points these at the mailpit service; prod supplies real values.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    # Envelope/From address, e.g. "isachore <no-reply@example.com>".
    smtp_from: str | None = None
    # STARTTLS upgrade on a plaintext connection (typical for port 587). Turn off
    # for a dev mailhog/mailpit that speaks plain SMTP.
    smtp_starttls: bool = True
    # Implicit TLS from connect (typical for port 465). Mutually exclusive with
    # smtp_starttls in practice.
    smtp_use_tls: bool = False

    # OpenID Connect single sign-on (Authentik, Authelia, Keycloak, ...). All
    # optional so the app boots without a provider, in which case the sign-in button
    # never renders and the OIDC endpoints 404; the flow is gated on
    # oidc_configured() in app/core/oidc.py, exactly as email is gated on
    # smtp_configured(). Unlike SMTP, a half-configured provider refuses boot
    # outside a dev environment (app/core/startup.py): two of the three set reads as
    # "not configured", so the button silently never renders and an operator who
    # clearly meant to turn SSO on gets no signal at all.
    #
    # The base url whose <issuer>/.well-known/openid-configuration resolves, and
    # which must equal the `iss` claim of the ID tokens it hands out. For Authentik
    # that is https://auth.example.com/application/o/<application-slug>/
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    # Name shown on the sign-in button ("Sign in with Authentik"). Cosmetic, like
    # totp_issuer, so it is deliberately NOT part of oidc_configured(): a deploy that
    # forgot it should still be able to sign in, under the generic default.
    oidc_provider_name: str = "SSO"
    # Space-separated scopes. "openid" is required by the protocol and "email" is
    # what an account is matched on, so this exists to widen the set rather than to
    # narrow it.
    oidc_scopes: str = "openid email profile"
    # Turn password sign-in off: hides the credential form and makes POST /auth/login return
    # 403. There is deliberately no in-app exemption, not even for admins, so recovering from
    # a broken provider means setting this back to false and restarting. Refuses boot outside
    # dev when no provider is configured, since that combination locks every user out.
    #
    # Deliberately scoped to *password sign-in* rather than described as "the only way in":
    # an account confirmation link (POST /confirm/{token}) still sets a password and opens a
    # session, which is the flow an admin starts by creating a user, and gating it here would
    # break account setup on a deployment that uses both. Nobody can reach it without a live
    # emailed token, so it is a second door with its own key rather than a bypass.
    oidc_only: bool = False


settings = Settings()


def is_dev_environment() -> bool:
    """Whether the deployment marker names a developer machine (see
    DEV_ENVIRONMENTS). Fail-safe: an unrecognised value reads as a real
    deployment."""
    return settings.environment.lower() in DEV_ENVIRONMENTS
