"""The app's in-process background scheduler.

This is the single place recurring, time-based jobs are registered (add more
`add_job` calls in `create_scheduler`). It's started and stopped by the FastAPI
lifespan in app/main.py. Prod runs a single web process today, so each job runs
once; if that ever changes (uvicorn `--workers`), gate the jobs with a
distributed lock (Redis is already wired) so they don't run per worker."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.invitations import run_expire_invitations

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    # Retire stale household invitations at the top of every hour.
    scheduler.add_job(
        run_expire_invitations,
        CronTrigger(minute=0, second=0, timezone="UTC"),
        id="expire-invitations",
        name="Expire stale household invitations",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    return scheduler
