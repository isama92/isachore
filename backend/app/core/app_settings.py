from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import APP_SETTINGS_ID, AppSettings


async def get_app_settings(session: AsyncSession) -> AppSettings:
    """The single server-settings row, created with defaults on first access.

    The initial migration seeds the row, but get-or-create keeps this robust for
    tests (which build the schema via create_all and never seed) and for any DB
    where the row is missing. The new row is flushed so its defaults are populated
    but not committed here; the caller owns the transaction.
    """
    settings = await session.get(AppSettings, APP_SETTINGS_ID)
    if settings is None:
        settings = AppSettings(id=APP_SETTINGS_ID)
        session.add(settings)
        await session.flush()
    return settings
