import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, RedisDep, SessionDep
from app.core.app_settings import get_app_settings
from app.core.config import settings
from app.core.email import NO_SMTP_DETAIL, send_email, smtp_configured
from app.core.rate_limit import enforce_test_email_cooldown
from app.models import AppSettings
from app.schemas import ServerSettingsRead, ServerSettingsUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


def _read(app_settings: AppSettings) -> ServerSettingsRead:
    return ServerSettingsRead(
        require_confirmation=app_settings.require_confirmation,
        smtp_configured=smtp_configured(),
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_from=settings.smtp_from,
    )


@router.get("", response_model=ServerSettingsRead)
async def read_settings(_: AdminUser, session: SessionDep) -> ServerSettingsRead:
    return _read(await get_app_settings(session))


@router.patch("", response_model=ServerSettingsRead)
async def update_settings(
    payload: ServerSettingsUpdate, _: AdminUser, session: SessionDep
) -> ServerSettingsRead:
    # Confirmation is useless without a way to send the email, so refuse to turn
    # it on until SMTP is configured in the environment.
    if payload.require_confirmation and not smtp_configured():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NO_SMTP_DETAIL)
    app_settings = await get_app_settings(session)
    app_settings.require_confirmation = payload.require_confirmation
    await session.commit()
    return _read(app_settings)


@router.post("/test-email", status_code=status.HTTP_204_NO_CONTENT)
async def send_test_email(admin: AdminUser, redis: RedisDep) -> None:
    if not smtp_configured():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NO_SMTP_DETAIL)
    await enforce_test_email_cooldown(redis, user_id=admin.id)
    try:
        await send_email(
            admin.email,
            "isachore test email",
            "This is a test email from isachore. If you received it, your SMTP "
            "settings are working.\n",
        )
    except Exception as exc:
        logger.exception("Failed to send test email to %s", admin.email)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the test email",
        ) from exc
