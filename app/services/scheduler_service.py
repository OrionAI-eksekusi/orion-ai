from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def proactive_check():
    try:
        logger.info("[PROACTIVE] Memulai pengecekan otomatis...")
        from app.services.ai_service import generate_briefing
        from app.routers.chat import send_fcm_notification, get_fcm_token

        token = get_fcm_token()
        if not token:
            logger.info("[PROACTIVE] Tidak ada FCM token, skip")
            return

        result = await generate_briefing()

        if result and result.get("urgent"):
            urgent = result["urgent"]
            count = len(urgent)
            if count > 0:
                first = urgent[0]
                sender = first.get("from", "Unknown")
                subject = first.get("subject", "")
                await send_fcm_notification(
                    title=f"📧 {count} Email Urgent!",
                    body=f"{sender}: {subject[:60]}",
                    data={"type": "email"}
                )
                logger.info(f"[PROACTIVE] Notif terkirim: {count} email urgent")

    except Exception as e:
        logger.error(f"[PROACTIVE ERROR] {e}")

def start_scheduler():
    try:
        scheduler.add_job(
            proactive_check,
            trigger=IntervalTrigger(minutes=30),
            id="proactive_check",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[SCHEDULER] Proactive Orion dimulai (30 menit)")
    except Exception as e:
        logger.error(f"[SCHEDULER ERROR] {e}")

def stop_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown()
    except Exception as e:
        logger.error(f"[SCHEDULER STOP ERROR] {e}")