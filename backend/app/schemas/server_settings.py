from pydantic import BaseModel


class ServerSettingsRead(BaseModel):
    require_confirmation: bool
    # Whether SMTP is configured in the environment (derived, not stored). The
    # admin UI uses it to disable the test-email button and warn that
    # confirmation can't be enabled without it.
    smtp_configured: bool


class ServerSettingsUpdate(BaseModel):
    require_confirmation: bool
