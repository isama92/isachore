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


settings = Settings()
