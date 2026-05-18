from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging
import re

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def proactive_check():
    """Cek email baru tanpa AI — hemat token!"""
    try:
        logger.info("[PROACTIVE] Cek email baru...")
        from app.services.gmail_service import get_gmail_service
        from app.routers.chat import send_fcm_notification, get_fcm_token

        token = get_fcm_token()
        if not token:
            return

        service = get_gmail_service()
        results = service.users().messages().list(
            userId='me',
            maxResults=5,
            labelIds=['INBOX', 'UNREAD'],
            q='is:unread newer_than:1h'
        ).execute()

        messages = results.get('messages', [])
        if not messages:
            logger.info("[PROACTIVE] Tidak ada email baru")
            return

        count = len(messages)
        detail = service.users().messages().get(
            userId='me', id=messages[0]['id'], format='metadata',
            metadataHeaders=['From', 'Subject']
        ).execute()

        headers = detail['payload']['headers']
        sender = next((h['value']
                      for h in headers if h['name'] == 'From'), 'Unknown')
        subject = next((h['value']
                       for h in headers if h['name'] == 'Subject'), '')
        sender_clean = sender.split('<')[0].strip().replace('"', '')

        await send_fcm_notification(
            title=f"📧 {count} Email Baru!",
            body=f"{sender_clean}: {subject[:60]}",
            data={"type": "email"}
        )
    except Exception as e:
        logger.error(f"[PROACTIVE ERROR] {e}")
        logger.info(f"[PROACTIVE] Notif terkirim: {count} email baru")


async def follow_up_check():
    """Cek customer WA yang belum dibalas — max 2x follow up"""
    try:
        logger.info("[FOLLOWUP] Mengecek pesan yang belum dibalas...")
        from app.services.database_service import get_unreplied_messages, mark_follow_up_sent
        from app.services.whatsapp_service import send_whatsapp_baileys
        from app.services.memory_service import get_customer_memory

        unreplied = get_unreplied_messages(hours=24)
        if not unreplied:
            logger.info("[FOLLOWUP] Tidak ada pesan yang perlu follow up")
            return

        for msg in unreplied:
            phone = msg["phone"]
            follow_up_count = msg.get("follow_up_count", 0)

            if follow_up_count >= 2:
                logger.info(f"[FOLLOWUP] {phone} sudah 2x follow up, skip")
                continue

            try:
                memory = get_customer_memory(phone)
                name = memory.get("name", "") if memory else ""

                if follow_up_count == 0:
                    if name:
                        follow_up = f"Halo {name}! 😊 Kami mau mastiin aja nih, ada yang bisa kami bantu lebih lanjut? Kami siap melayani kamu kapanpun! 🙏"
                    else:
                        follow_up = "Halo! 😊 Kami mau mastiin aja nih, ada yang bisa kami bantu lebih lanjut? Kami siap melayani kapanpun! 🙏"
                else:
                    if name:
                        follow_up = f"Halo {name}, just checking in nih 😊 Kalau ada yang mau ditanyain atau butuh bantuan, kami selalu siap ya! 🙏"
                    else:
                        follow_up = "Halo! Just checking in nih 😊 Kalau ada yang mau ditanyain atau butuh bantuan, kami selalu siap ya! 🙏"

                send_whatsapp_baileys(phone, follow_up)
                mark_follow_up_sent(phone)
            except Exception as e:
                logger.error(f"[FOLLOWUP ERROR] {phone}: {e}")
                logger.info(
                    f"[FOLLOWUP] Follow up ke-{follow_up_count+1} terkirim ke {phone}")

    except Exception as e:
        logger.error(f"[FOLLOWUP CHECK ERROR] {e}")


async def brain_follow_up_check():
    """Cek Personal Brain follow up yang jatuh tempo — kirim FCM + WA ke kontak"""
    try:
        logger.info("[BRAIN FOLLOWUP] Cek Personal Brain follow up...")
        from app.services.database_service import get_all_active_users
        from app.services.memory_service import get_pending_follow_ups, mark_brain_follow_up_sent
        from app.services.whatsapp_service import send_whatsapp_baileys
        from app.routers.chat import send_fcm_notification

        users = get_all_active_users()
        if not users:
            users = [{"user_id": "default", "name": ""}]

        for user in users:
            user_id = user["user_id"]
            user_name = user.get("name", "")

            try:
                pending = get_pending_follow_ups(user_id)
                if not pending:
                    continue

                for item in pending:
                    name = item["name"]
                    notes = item["notes"]
                    follow_up_count = item.get("follow_up_count", 0)

                    # ✅ Kirim FCM notif ke owner
                    await send_fcm_notification(
                        title=f"⏰ Follow Up: {name}",
                        body=f"Waktunya follow up {name}! {notes[:60]}",
                        data={
                            "type": "brain_followup",
                            "entity_name": name,
                            "follow_up_count": str(follow_up_count + 1)
                        },
                        user_id=user_id
                    )

                    # ✅ Cari nomor WA dari notes menggunakan regex
                    phone_match = re.search(
                        r'(?:wa|whatsapp|hp|telp|phone|nomor)?[:\s]*(\+?62\d{8,13}|08\d{8,13})',
                        notes,
                        re.IGNORECASE)

                    if phone_match:
                        phone = phone_match.group(1).strip()
                        phone = phone.replace(
                            "+",
                            "").replace(
                            "-",
                            "").replace(
                            " ",
                            "")
                        if phone.startswith("0"):
                            phone = "62" + phone[1:]
                        elif not phone.startswith("62"):
                            phone = "62" + phone

                        # ✅ Kirim WA follow up ke kontak
                        if follow_up_count == 0:
                            wa_msg = f"Halo {name}! 😊\n\nSaya {user_name} mau follow up nih. Gimana kabarnya? Ada yang bisa saya bantu atau diskusikan? 🙏"
                        else:
                            wa_msg = f"Halo {name},\n\nSaya {user_name} kembali follow up ya. Semoga semuanya baik-baik saja! Ada update yang bisa kita diskusikan? 😊"

                        try:
                            send_whatsapp_baileys(phone, wa_msg)
                        except Exception as wa_err:
                            logger.error(
                                f"[BRAIN FOLLOWUP WA ERROR] {name}: {wa_err}")
                            logger.info(
                                f"[BRAIN FOLLOWUP] WA terkirim ke {name} ({phone})")
                    else:
                        logger.info(
                            f"[BRAIN FOLLOWUP] {name} tidak punya nomor WA di notes, skip kirim WA")
            except Exception as e:
                logger.error(f"[BRAIN FOLLOWUP ERROR] user {user_id}: {e}")

                mark_brain_follow_up_sent(user_id, name)
                logger.info(
                    f"[BRAIN FOLLOWUP] Follow up selesai: {name} (user: {user_id})")

    except Exception as e:
        logger.error(f"[BRAIN FOLLOWUP CHECK ERROR] {e}")


async def payment_reminder_check():
    """Cek invoice jatuh tempo dan kirim WA reminder otomatis — max 3x"""
    try:
        logger.info("[PAYMENT] Cek invoice jatuh tempo...")
        from app.services.payment_service import (
            get_due_invoices, increment_reminder_count,
            format_amount, init_payment_db
        )
        from app.services.database_service import get_all_active_users
        from app.services.whatsapp_service import send_whatsapp_baileys
        from app.routers.chat import send_fcm_notification

        init_payment_db()
        users = get_all_active_users()
        if not users:
            users = [{"user_id": "default"}]

        for user in users:
            user_id = user["user_id"]
            if not user_id or user_id == "default":
                continue

            try:
                due_invoices = get_due_invoices(user_id)
                if not due_invoices:
                    logger.info(
                        f"[PAYMENT] Tidak ada invoice jatuh tempo untuk {user_id}")
                    continue

                for inv in due_invoices:
                    phone = inv.get("customer_phone", "")
                    name = inv.get("customer_name", "Customer")
                    amount = format_amount(inv.get("amount", 0))
                    inv_number = inv.get("invoice_number", "")
                    due_date = inv.get("due_date", "")
                    reminder_count = inv.get("reminder_count", 0)

                    if reminder_count == 0:
                        wa_msg = (
                            f"Halo {name}! 😊\n\n"
                            f"Kami mau mengingatkan tagihan berikut ya:\n\n"
                            f"📄 *Invoice:* {inv_number}\n"
                            f"💰 *Nominal:* {amount}\n"
                            f"📅 *Jatuh Tempo:* {due_date}\n\n"
                            f"Mohon segera dilakukan pembayaran ya. "
                            f"Kalau ada kendala jangan sungkan hubungi kami! 🙏"
                        )
                    elif reminder_count == 1:
                        wa_msg = (
                            f"Halo {name} 😊\n\n"
                            f"Kami mau follow up tagihan:\n\n"
                            f"📄 *Invoice:* {inv_number}\n"
                            f"💰 *Nominal:* {amount}\n"
                            f"📅 *Jatuh Tempo:* {due_date}\n\n"
                            f"Apakah ada kendala pembayaran? "
                            f"Kami siap bantu carikan solusinya! 🙏"
                        )
                    else:
                        wa_msg = (
                            f"Halo {name},\n\n"
                            f"Ini reminder terakhir untuk:\n\n"
                            f"📄 *Invoice:* {inv_number}\n"
                            f"💰 *Nominal:* {amount}\n"
                            f"📅 *Jatuh Tempo:* {due_date}\n\n"
                            f"Mohon segera konfirmasi pembayaran atau "
                            f"hubungi kami langsung. Terima kasih! 🙏"
                        )

                    if phone:
                        try:
                            send_whatsapp_baileys(phone, wa_msg)
                        except Exception as e:
                            logger.error(f"[PAYMENT WA ERROR] {e}")
                            logger.info(
                                f"[PAYMENT] WA reminder terkirim ke {name} ({phone})")

                    increment_reminder_count(inv_number, user_id)

                    await send_fcm_notification(
                        title=f"💰 Reminder Invoice: {name}",
                        body=f"{inv_number} — {amount} — Reminder ke-{reminder_count+1}",
                        data={"type": "payment_reminder", "invoice": inv_number},
                        user_id=user_id
                    )

            except Exception as e:
                logger.error(f"[PAYMENT ERROR] user {user_id}: {e}")
                logger.info(f"[PAYMENT] {len(due_invoices)} reminder terkirim untuk {user_id}")

    except Exception as e:
        logger.error(f"[PAYMENT REMINDER ERROR] {e}")


async def daily_intelligence_briefing():
    """Kirim Daily Intelligence Briefing setiap pagi jam 06.00 WIB"""
    try:
        logger.info("[BRIEFING] Memulai Daily Intelligence Briefing...")

        from app.services.gmail_service import get_gmail_service
        from app.services.database_service import get_wa_messages, get_all_active_users
        from app.services.calendar_service import get_upcoming_events
        from app.routers.chat import send_fcm_notification
        from app.services.ai_provider import call_llm
        import httpx
        from datetime import datetime
        import os

        user_city = os.getenv("USER_CITY", "Jakarta")
        weather_text = "Tidak tersedia"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get(
                    f"https://wttr.in/{user_city}?format=%C+%t+%h",
                    headers={"User-Agent": "curl/7.68.0"}
                )
                if res.status_code == 200:
                    weather_text = res.text.strip()
        except Exception:
            pass

        email_count = 0
        urgent_emails = []
        try:
            service = get_gmail_service()
            results = service.users().messages().list(
                userId='me',
                maxResults=10,
                labelIds=['INBOX', 'UNREAD'],
                q='is:unread newer_than:1d'
            ).execute()
            messages = results.get('messages', [])
            email_count = len(messages)

            for msg in messages[:3]:
                detail = service.users().messages().get(
                    userId='me', id=msg['id'], format='metadata',
                    metadataHeaders=['From', 'Subject']
                ).execute()
                headers = detail['payload']['headers']
                sender = next((h['value']
                              for h in headers if h['name'] == 'From'), '')
                subject = next(
                    (h['value'] for h in headers if h['name'] == 'Subject'), '')
                sender_clean = sender.split('<')[0].strip().replace('"', '')
                urgent_emails.append(f"• {sender_clean}: {subject[:50]}")
        except Exception as e:
            logger.error(f"[BRIEFING EMAIL] {e}")

        wa_messages = get_wa_messages(limit=20)
        wa_unreplied = [m for m in wa_messages if not m.get("replied")]
        wa_count = len(wa_unreplied)

        events_today = []
        try:
            cal_result = get_upcoming_events(user_id, max_results=5)
            events = cal_result.get('events', [])
            today = datetime.now().strftime("%Y-%m-%d")
            for e in events:
                start = e.get("start", "")
                if today in str(start):
                    events_today.append(
                        f"• {e.get('title', '')} — {start[11:16]}")
        except Exception:
            pass

        quote = ""
        try:
            quote = await call_llm(
                "Kamu adalah generator quote motivasi bisnis. Berikan 1 quote motivasi singkat dalam Bahasa Indonesia, maksimal 15 kata. Hanya tulis quotenya saja tanpa tanda kutip.",
                "Berikan quote motivasi hari ini"
            )
        except Exception:
            quote = "Hari ini adalah kesempatan baru untuk jadi lebih baik!"

        business_news = ""
        try:
            business_news = await call_llm(
                "Kamu adalah analis bisnis Indonesia. Berikan 2-3 poin berita/insight bisnis yang relevan hari ini dalam Bahasa Indonesia. Format: bullet point singkat. Maksimal 50 kata total.",
                f"Berikan insight bisnis hari ini, {datetime.now().strftime('%d %B %Y')}"
            )
        except Exception:
            business_news = "• Pantau pergerakan kurs Rupiah hari ini\n• Cek update kebijakan ekspor terbaru"

        now = datetime.now()
        day_id = ["Senin", "Selasa", "Rabu", "Kamis",
                  "Jumat", "Sabtu", "Minggu"][now.weekday()]
        date_str = now.strftime(f"{day_id}, %d %B %Y")

        users = get_all_active_users()
        if not users:
            users = [{"user_id": "default", "name": os.getenv("USER_NAME", "Bos"),
                      "city": user_city, "phone": os.getenv("USER_PHONE", "")}]

        for user in users:
            user_id = user["user_id"]
            user_name = user.get("name") or os.getenv("USER_NAME", "Bos")
            user_phone = user.get("phone") or os.getenv("USER_PHONE", "")
            city = user.get("city") or user_city

            brain_reminder = ""
            try:
                from app.services.memory_service import get_pending_follow_ups
                pending = get_pending_follow_ups(user_id)
                if pending:
                    names = [p["name"] for p in pending[:3]]
                    brain_reminder = f"\n\n⏰ FOLLOW UP HARI INI:\n" + \
                        "\n".join([f"• {n}" for n in names])
            except Exception:
                pass

            invoice_reminder = ""
            try:
                from app.services.payment_service import get_due_invoices, format_amount, init_payment_db
                init_payment_db()
                due_invoices = get_due_invoices(user_id)
                if due_invoices:
                    invoice_reminder = f"\n\n💰 TAGIHAN JATUH TEMPO:\n"
                    for inv in due_invoices[:3]:
                        invoice_reminder += f"• {inv['customer_name']} — {format_amount(inv['amount'])}\n"
            except Exception:
                pass

            briefing_text = f"""☀️ Selamat Pagi, {user_name}!
━━━━━━━━━━━━━━━

📅 {date_str}
🌤️ Cuaca {city}: {weather_text}

📧 EMAIL HARI INI:
{f"Ada {email_count} email baru" if email_count > 0 else "Inbox bersih ✨"}
{chr(10).join(urgent_emails) if urgent_emails else ""}

💬 WHATSAPP:
{f"Ada {wa_count} pesan belum dibalas" if wa_count > 0 else "Semua pesan sudah dibalas ✅"}

📋 AGENDA HARI INI:
{chr(10).join(events_today) if events_today else "• Tidak ada jadwal hari ini"}{brain_reminder}{invoice_reminder}

📰 INSIGHT BISNIS:
{business_news}

💡 QUOTE HARI INI:
"{quote}"

━━━━━━━━━━━━━━━
Semangat hari ini! 💪🔥
— Orion AI"""

            await send_fcm_notification(
                title=f"☀️ Selamat Pagi, {user_name}!",
                body=f"📧 {email_count} email | 💬 {wa_count} WA | {weather_text}",
                data={"type": "briefing", "content": briefing_text[:500]},
                user_id=user_id
            )

            try:
                from app.services.whatsapp_service import send_whatsapp_baileys
                if user_phone:
                    send_whatsapp_baileys(user_phone, briefing_text)
            except Exception as e:
                logger.error(f"[BRIEFING WA] {e}")
                logger.info(f"[BRIEFING] WA terkirim ke {user_phone}")

    except Exception as e:
        logger.error(f"[BRIEFING ERROR] {e}")
        logger.info("[BRIEFING] Daily Intelligence Briefing selesai!")


async def generate_weekly_report():
    """Generate laporan mingguan otomatis setiap Senin jam 07.00 WIB"""
    try:
        logger.info("[REPORT] Memulai generate laporan mingguan...")

        from app.services.ai_service import generate_briefing, extract_tasks
        from app.services.database_service import get_wa_messages
        from app.services.memory_service import get_all_customers
        from app.services.gmail_service import send_email_with_attachment
        from app.routers.chat import send_fcm_notification
        from datetime import datetime
        import os

        briefing = await generate_briefing()
        tasks_data = await extract_tasks()
        wa_messages = get_wa_messages(limit=50)
        customers = get_all_customers()

        urgent_count = len(briefing.get("urgent", []))
        total_email = urgent_count + \
            len(briefing.get("bisa_nanti", [])) + len(briefing.get("arsip", []))

        tasks = tasks_data.get("tasks", [])
        done_tasks = [t for t in tasks if t.get("done")]
        pending_tasks = [t for t in tasks if not t.get("done")]
        high_priority = [
            t for t in pending_tasks if t.get("priority") == "high"]

        total_wa = len(wa_messages)
        replied_wa = len([m for m in wa_messages if m.get("replied")])

        pdf_path = await _generate_report_pdf(
            briefing=briefing,
            tasks=tasks,
            wa_messages=wa_messages,
            customers=customers,
            urgent_count=urgent_count,
            total_email=total_email,
            total_wa=total_wa,
            replied_wa=replied_wa,
            done_tasks=done_tasks,
            pending_tasks=pending_tasks,
            high_priority=high_priority,
        )

        boss_email = os.getenv("BOSS_EMAIL", "")
        if boss_email and pdf_path:
            week = datetime.now().strftime("%d %B %Y")
            send_email_with_attachment(
                to=boss_email,
                subject=f"📊 Laporan Mingguan Orion AI — {week}",
                body=f"""Halo,

Terlampir laporan mingguan otomatis dari Orion AI.

Ringkasan:
- Total email masuk: {total_email}
- Email urgent: {urgent_count}
- Pesan WA: {total_wa} ({replied_wa} dibalas)
- Task selesai: {len(done_tasks)}
- Task pending: {len(pending_tasks)}

Laporan lengkap ada di attachment PDF.

Salam,
Orion AI 🤖""",
                file_path=pdf_path,
                filename=f"Laporan_Mingguan_{datetime.now().strftime('%Y%m%d')}.pdf"
            )
    except Exception as e:
        logger.error(f"[REPORT ERROR] {e}")
        logger.info(f"[REPORT] Laporan terkirim ke {boss_email}")

        await send_fcm_notification(
            title="📊 Laporan Mingguan Siap!",
            body=f"Email: {total_email} | WA: {total_wa} | Task: {len(done_tasks)} selesai",
            data={"type": "report"}
        )


async def _generate_report_pdf(
    briefing, tasks, wa_messages, customers,
    urgent_count, total_email, total_wa, replied_wa,
    done_tasks, pending_tasks, high_priority
) -> str:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_CENTER
        from datetime import datetime
        import os

        os.makedirs("/tmp/reports", exist_ok=True)
        filename = f"/tmp/reports/laporan_{datetime.now().strftime('%Y%m%d%H%M')}.pdf"

        doc = SimpleDocTemplate(filename, pagesize=A4,
                                rightMargin=2*cm, leftMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)

        primary = colors.HexColor("#1A3A8F")
        success = colors.HexColor("#2D8B4E")
        danger = colors.HexColor("#FF4444")
        warning = colors.HexColor("#F59E0B")
        gray = colors.HexColor("#6B7280")
        light = colors.HexColor("#F3F4F6")

        story = []

        story.append(Paragraph(
            "<font size='22' color='#1A3A8F'><b>📊 LAPORAN MINGGUAN</b></font>",
            ParagraphStyle("center", alignment=TA_CENTER)
        ))
        story.append(
            Paragraph(
                f"<font size='12' color='#6B7280'>Orion AI Execution System • {datetime.now().strftime('%d %B %Y %H:%M')}</font>",
                ParagraphStyle(
                    "center",
                    alignment=TA_CENTER)))
        story.append(
            HRFlowable(
                width="100%",
                thickness=2,
                color=primary,
                spaceAfter=16))

        story.append(
            Paragraph(
                "<b>📈 RINGKASAN</b>",
                ParagraphStyle(
                    "h2",
                    fontSize=13,
                    textColor=primary,
                    spaceAfter=8)))

        summary_data = [
            ["📧 Total Email", "💬 WA Masuk", "✅ Task Selesai", "⏳ Task Pending"],
            [str(total_email), str(total_wa), str(len(done_tasks)), str(len(pending_tasks))],
        ]
        summary_table = Table(summary_data, colWidths=[4.25*cm]*4)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 1), (-1, 1), 18),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0, 1), (0, 1), primary),
            ('TEXTCOLOR', (1, 1), (1, 1), success),
            ('TEXTCOLOR', (2, 1), (2, 1), success),
            ('TEXTCOLOR', (3, 1), (3, 1), warning),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 0.5*cm))

        story.append(
            Paragraph(
                "<b>📧 ANALISA EMAIL</b>",
                ParagraphStyle(
                    "h2",
                    fontSize=13,
                    textColor=primary,
                    spaceAfter=8)))
        email_data = [
            ["Kategori", "Jumlah", "Status"],
            ["🔴 Urgent", str(urgent_count), "Perlu dibalas segera"],
            ["🟡 Bisa Nanti", str(len(briefing.get("bisa_nanti", []))), "Bisa ditunda"],
            ["📦 Arsip", str(len(briefing.get("arsip", []))), "Auto arsip"],
        ]
        email_table = Table(email_data, colWidths=[6*cm, 3*cm, 8*cm])
        email_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(email_table)
        story.append(Spacer(1, 0.5*cm))

        story.append(
            Paragraph(
                "<b>💬 ANALISA WHATSAPP</b>",
                ParagraphStyle(
                    "h2",
                    fontSize=13,
                    textColor=success,
                    spaceAfter=8)))
        wa_rate = int((replied_wa/total_wa*100)) if total_wa > 0 else 0
        wa_data = [
            ["Metrik", "Nilai"],
            ["Total Pesan Masuk", str(total_wa)],
            ["Dibalas Otomatis", str(replied_wa)],
            ["Response Rate", f"{wa_rate}%"],
            ["Total Customer", str(len(customers))],
        ]
        wa_table = Table(wa_data, colWidths=[9*cm, 8*cm])
        wa_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), success),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(wa_table)
        story.append(Spacer(1, 0.5*cm))

        if high_priority:
            story.append(
                Paragraph(
                    "<b>⚠️ TASK PRIORITAS TINGGI</b>",
                    ParagraphStyle(
                        "h2",
                        fontSize=13,
                        textColor=danger,
                        spaceAfter=8)))
            task_data = [["Task", "Dari", "Deadline"]]
            for t in high_priority[:5]:
                task_data.append([
                    t.get("title", "")[:40],
                    t.get("from", "")[:20],
                    t.get("due", "-")[:16] if t.get("due") else "-"
                ])
            task_table = Table(task_data, colWidths=[8*cm, 5*cm, 4*cm])
            task_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), danger),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF5F5")]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 7),
            ]))
            story.append(task_table)
            story.append(Spacer(1, 0.5*cm))

        if customers:
            story.append(
                Paragraph(
                    "<b>👥 CUSTOMER AKTIF</b>",
                    ParagraphStyle(
                        "h2",
                        fontSize=13,
                        textColor=primary,
                        spaceAfter=8)))
            cust_data = [["Nama", "Phone"]]
            for c in customers[:8]:
                cust_data.append([
                    c.get("name", "Unknown")[:30],
                    c.get("phone", "")[:20],
                ])
            cust_table = Table(cust_data, colWidths=[9*cm, 8*cm])
            cust_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), primary),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 7),
            ]))
            story.append(cust_table)
            story.append(Spacer(1, 0.5*cm))

        story.append(
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=gray,
                spaceAfter=6))
        story.append(
            Paragraph(
                f"<font size='9' color='#6B7280'>Laporan ini dibuat otomatis oleh Orion AI • {datetime.now().strftime('%d/%m/%Y %H:%M')} WIB</font>",
                ParagraphStyle(
                    "center",
                    alignment=TA_CENTER)))

        doc.build(story)
    except Exception as e:
        logger.error(f"[REPORT PDF ERROR] {e}")
        logger.info(f"[REPORT] PDF berhasil: {filename}")
        return filename

        return ""


def start_scheduler():
    try:
        scheduler.add_job(
            proactive_check,
            trigger=IntervalTrigger(minutes=30),
            id="proactive_check",
            replace_existing=True,
        )

        scheduler.add_job(
            follow_up_check,
            trigger=IntervalTrigger(hours=1),
            id="follow_up_check",
            replace_existing=True,
        )

        scheduler.add_job(
            generate_weekly_report,
            trigger=CronTrigger(day_of_week="mon", hour=0, minute=0),
            id="weekly_report",
            replace_existing=True,
        )

        scheduler.add_job(
            daily_intelligence_briefing,
            trigger=CronTrigger(hour=23, minute=0),
            id="daily_briefing",
            replace_existing=True,
        )

        scheduler.add_job(
            brain_follow_up_check,
            trigger=CronTrigger(hour=1, minute=0),
            id="brain_followup",
            replace_existing=True,
        )

        scheduler.add_job(
            payment_reminder_check,
            trigger=CronTrigger(hour=2, minute=0),
            id="payment_reminder",
            replace_existing=True,
        )

    except Exception as e:
        logger.error(f"[SCHEDULER ERROR] {e}")
    logger.info(
        "[SCHEDULER] Semua job dimulai:\n"
        "  - Proactive: 30 menit\n"
        "  - Follow up WA: 1 jam (max 2x) via Baileys\n"
        "  - Report: Senin 07.00 WIB\n"
        "  - Briefing: 06.00 pagi\n"
        "  - Brain Follow Up: 08.00 pagi + WA otomatis ke kontak\n"
        "  - Payment Reminder: 09.00 pagi via Baileys"
    )


def stop_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown()
    except Exception as e:
        logger.error(f"[SCHEDULER STOP ERROR] {e}")
