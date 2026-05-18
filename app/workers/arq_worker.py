import os
import logging
from arq.connections import RedisSettings
from arq.cron import cron

logger = logging.getLogger(__name__)

REDIS_URL = (
    os.environ.get("REDIS_URL") or
    os.environ.get("REDIS_PUBLIC_URL") or
    "redis://localhost:6379"
)


# ─── JOBS ────────────────────────────────────────────

async def job_proactive_check(ctx):
    try:
        from app.services.scheduler_service import proactive_check
        await proactive_check()
    except Exception as e:
        logger.error(f"[ARQ] proactive_check error: {e}")


async def job_follow_up_check(ctx):
    try:
        from app.services.scheduler_service import follow_up_check
        await follow_up_check()
    except Exception as e:
        logger.error(f"[ARQ] follow_up_check error: {e}")


async def job_daily_briefing(ctx):
    try:
        from app.services.database_service import get_all_active_users
        from app.services.calendar_service import get_upcoming_events
        from app.services.scheduler_service import daily_intelligence_briefing
        await daily_intelligence_briefing()
    except Exception as e:
        logger.error(f"[ARQ] daily_briefing error: {e}")


async def job_brain_followup(ctx):
    try:
        from app.services.scheduler_service import brain_follow_up_check
        await brain_follow_up_check()
    except Exception as e:
        logger.error(f"[ARQ] brain_followup error: {e}")


async def job_payment_reminder(ctx):
    try:
        from app.services.scheduler_service import payment_reminder_check
        await payment_reminder_check()
    except Exception as e:
        logger.error(f"[ARQ] payment_reminder error: {e}")


async def job_weekly_report(ctx):
    try:
        from app.services.scheduler_service import generate_weekly_report
        await generate_weekly_report()
    except Exception as e:
        logger.error(f"[ARQ] weekly_report error: {e}")


# ─── STARTUP ─────────────────────────────────────────

async def startup(ctx):
    from app.services.database_service import init_db
    from app.services.memory_service import init_memory_db
    try:
        init_db()
        init_memory_db()
        logger.info("[ARQ WORKER] ✅ Database initialized")
    except Exception as e:
        logger.error(f"[ARQ WORKER] DB init error: {e}")


# ─── WORKER SETTINGS ─────────────────────────────────

class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL") or
        os.environ.get("REDIS_PUBLIC_URL") or
        "redis://localhost:6379"
    )
    on_startup = startup
    functions = [
        job_proactive_check,
        job_follow_up_check,
        job_daily_briefing,
        job_brain_followup,
        job_payment_reminder,
        job_weekly_report,
    ]
    cron_jobs = [
        cron(job_proactive_check, minute={0, 30}),
        cron(job_follow_up_check, minute=0),
        cron(job_daily_briefing, hour=23, minute=0),
        cron(job_brain_followup, hour=1, minute=0),
        cron(job_payment_reminder, hour=2, minute=0),
        cron(job_weekly_report, weekday=0, hour=0, minute=0),
    ]
