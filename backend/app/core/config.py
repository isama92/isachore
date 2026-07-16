from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Deployment marker (e.g. "dev" / "prod"). Informational only; cookie
    # security is controlled by cookies_secure below, not by this value.
    environment: str = "dev"

    # Auth cookies get the Secure flag (HTTPS only) by default, so a deploy that
    # configures nothing fails closed. Local dev is served over plain HTTP, so
    # it must opt out explicitly with COOKIES_SECURE=false.
    cookies_secure: bool = True

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

    # Trust the client IP from the X-Forwarded-For header. Off by default (safe
    # for direct/dev access); turn on only behind a trusted reverse proxy such as
    # the prod nginx, which sets the header.
    trust_forwarded_for: bool = False


settings = Settings()
