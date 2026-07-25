from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import APP_SETTINGS_ID, AppSettings


async def get_app_settings(session: AsyncSession) -> AppSettings:
    """The single server-settings row, created with defaults on first access.

    Get-or-create is the ONLY thing that puts this row in the database: no
    migration seeds it, so on a fresh install the first caller creates it. Do not
    "simplify" the create branch away as defensive code. The new row is flushed so
    its defaults are populated but not committed here; the caller owns the
    transaction.
    """
    settings = await session.get(AppSettings, APP_SETTINGS_ID)
    if settings is None:
        settings = AppSettings(id=APP_SETTINGS_ID)
        session.add(settings)
        await session.flush()
    return settings
