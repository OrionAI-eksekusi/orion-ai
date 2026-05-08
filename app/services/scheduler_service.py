from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging

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
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        sender_clean = sender.split('<')[0].strip().replace('"', '')

        await send_fcm_notification(
            title=f"📧 {count} Email Baru!",
            body=f"{sender_clean}: {subject[:60]}",
            data={"type": "email"}
        )
        logger.info(f"[PROACTIVE] Notif terkirim: {count} email baru")

    except Exception as e:
        logger.error(f"[PROACTIVE ERROR] {e}")


async def follow_up_check():
    """Cek customer WA yang belum dibalas lebih dari 24 jam"""
    try:
        logger.info("[FOLLOWUP] Mengecek pesan yang belum dibalas...")
        from app.services.database_service import get_unreplied_messages, mark_follow_up_sent
        from app.services.whatsapp_service import send_whatsapp
        from app.services.memory_service import get_customer_memory

        unreplied = get_unreplied_messages(hours=24)

        if not unreplied:
            logger.info("[FOLLOWUP] Tidak ada pesan yang perlu follow up")
            return

        for msg in unreplied:
            phone = msg["phone"]
            try:
                memory = get_customer_memory(phone)
                name = memory.get("name", "") if memory else ""

                if name:
                    follow_up = f"Halo {name}! 😊 Ada yang bisa kami bantu? Kami siap melayani kamu."
                else:
                    follow_up = "Halo! 😊 Ada yang bisa kami bantu? Kami siap melayani Anda."

                send_whatsapp(phone, follow_up)
                mark_follow_up_sent(phone)
                logger.info(f"[FOLLOWUP] Follow up terkirim ke {phone}")

            except Exception as e:
                logger.error(f"[FOLLOWUP ERROR] {phone}: {e}")

    except Exception as e:
        logger.error(f"[FOLLOWUP CHECK ERROR] {e}")


async def generate_weekly_report():
    """Generate laporan mingguan otomatis"""
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
        total_email = urgent_count + len(briefing.get("bisa_nanti", [])) + len(briefing.get("arsip", []))

        tasks = tasks_data.get("tasks", [])
        done_tasks = [t for t in tasks if t.get("done")]
        pending_tasks = [t for t in tasks if not t.get("done")]
        high_priority = [t for t in pending_tasks if t.get("priority") == "high"]

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
            logger.info(f"[REPORT] Laporan terkirim ke {boss_email}")

        await send_fcm_notification(
            title="📊 Laporan Mingguan Siap!",
            body=f"Email: {total_email} | WA: {total_wa} | Task: {len(done_tasks)} selesai",
            data={"type": "report"}
        )

    except Exception as e:
        logger.error(f"[REPORT ERROR] {e}")


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
        story.append(Paragraph(
            f"<font size='12' color='#6B7280'>Orion AI Execution System • {datetime.now().strftime('%d %B %Y %H:%M')}</font>",
            ParagraphStyle("center", alignment=TA_CENTER)
        ))
        story.append(HRFlowable(width="100%", thickness=2, color=primary, spaceAfter=16))

        # Summary
        story.append(Paragraph("<b>📈 RINGKASAN</b>",
            ParagraphStyle("h2", fontSize=13, textColor=primary, spaceAfter=8)))

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

        # Email
        story.append(Paragraph("<b>📧 ANALISA EMAIL</b>",
            ParagraphStyle("h2", fontSize=13, textColor=primary, spaceAfter=8)))

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

        # WA
        story.append(Paragraph("<b>💬 ANALISA WHATSAPP</b>",
            ParagraphStyle("h2", fontSize=13, textColor=success, spaceAfter=8)))

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

        # Task prioritas tinggi
        if high_priority:
            story.append(Paragraph("<b>⚠️ TASK PRIORITAS TINGGI</b>",
                ParagraphStyle("h2", fontSize=13, textColor=danger, spaceAfter=8)))

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

        # Customer aktif
        if customers:
            story.append(Paragraph("<b>👥 CUSTOMER AKTIF</b>",
                ParagraphStyle("h2", fontSize=13, textColor=primary, spaceAfter=8)))

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

        # Footer
        story.append(HRFlowable(width="100%", thickness=0.5, color=gray, spaceAfter=6))
        story.append(Paragraph(
            f"<font size='9' color='#6B7280'>Laporan ini dibuat otomatis oleh Orion AI • {datetime.now().strftime('%d/%m/%Y %H:%M')} WIB</font>",
            ParagraphStyle("center", alignment=TA_CENTER)
        ))

        doc.build(story)
        logger.info(f"[REPORT] PDF berhasil: {filename}")
        return filename

    except Exception as e:
        logger.error(f"[REPORT PDF ERROR] {e}")
        return ""


def start_scheduler():
    try:
        # Job 1: Proactive email check tiap 30 menit — hemat token
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

        # Job 3: TEST — laporan tiap 2 menit
        scheduler.add_job(
            generate_weekly_report,
            trigger=IntervalTrigger(minutes=2),
            id="weekly_report",
            replace_existing=True,
        )

        scheduler.start()
        logger.info("[SCHEDULER] Semua job dimulai (proactive: 30 menit, follow up: 1 jam, report: 2 menit TEST)")

    except Exception as e:
        logger.error(f"[SCHEDULER ERROR] {e}")


def stop_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown()
    except Exception as e:
        logger.error(f"[SCHEDULER STOP ERROR] {e}")