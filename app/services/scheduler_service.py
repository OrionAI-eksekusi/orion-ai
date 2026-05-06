from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def proactive_check():
    """Cek email urgent tiap 30 menit"""
    try:
        logger.info("[PROACTIVE] Memulai pengecekan email otomatis...")
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


async def follow_up_check():
    """Cek customer WA yang belum dibalas lebih dari 24 jam"""
    try:
        logger.info("[FOLLOWUP] Mengecek pesan yang belum dibalas...")
        from app.services.database_service import get_unreplied_messages, mark_follow_up_sent
        from app.services.whatsapp_service import send_whatsapp
        from app.services.memory_service import get_customer_memory

        # Ambil pesan yang belum dibalas lebih dari 24 jam
        unreplied = get_unreplied_messages(hours=24)

        if not unreplied:
            logger.info("[FOLLOWUP] Tidak ada pesan yang perlu follow up")
            return

        for msg in unreplied:
            phone = msg["phone"]
            try:
                # Ambil nama customer dari memory
                memory = get_customer_memory(phone)
                name = memory.get("name", "") if memory else ""

                # Buat pesan follow up personal
                if name:
                    follow_up = f"Halo {name}! 😊 Ada yang bisa kami bantu? Kami siap melayani kamu."
                else:
                    follow_up = "Halo! 😊 Ada yang bisa kami bantu? Kami siap melayani Anda."

                # Kirim follow up
                send_whatsapp(phone, follow_up)
                mark_follow_up_sent(phone)
                logger.info(f"[FOLLOWUP] Follow up terkirim ke {phone}")

            except Exception as e:
                logger.error(f"[FOLLOWUP ERROR] {phone}: {e}")

    except Exception as e:
        logger.error(f"[FOLLOWUP CHECK ERROR] {e}")


def start_scheduler():
    try:
        # Job 1: Proactive email check tiap 30 menit
        scheduler.add_job(
            proactive_check,
            trigger=IntervalTrigger(minutes=30),
            id="proactive_check",
            replace_existing=True,
        )

        # Job 2: Follow up WA tiap 1 jam
        scheduler.add_job(
            follow_up_check,
            trigger=IntervalTrigger(hours=1),
            id="follow_up_check",
            replace_existing=True,
        )

        scheduler.start()
        logger.info("[SCHEDULER] Proactive Orion dimulai (email: 30 menit, follow up: 1 jam)")

    except Exception as e:
        logger.error(f"[SCHEDULER ERROR] {e}")


def stop_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown()
    except Exception as e:
        logger.error(f"[SCHEDULER STOP ERROR] {e}")