from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The single settings row always lives at this id (see get_app_settings).
APP_SETTINGS_ID = 1


class AppSettings(Base):
    """Runtime-mutable, server-wide settings (as opposed to the env-driven,
    boot-time Settings in app.core.config). A single row, id=1, fetched/created
    via get_app_settings. Kept as a typed table rather than a key-value store
    while there is only a handful of flags."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    # When true, a newly created user starts waiting_confirmation and must set
    # their password via an emailed link before they can log in. When false,
    # admins set the password directly and the user is active immediately.
    require_confirmation: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
