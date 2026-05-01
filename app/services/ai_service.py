import os
import json
import re
from dotenv import load_dotenv
from app.services.ai_provider import call_llm, parse_json_response

load_dotenv()


async def process_command(message: str):
    email_keywords = ['email', 'balas', 'inbox', 'pesan masuk', 'surat']
    is_email_command = any(word in message.lower() for word in email_keywords)

    email_context = ""
    emails = []
    target_email = None

    if is_email_command:
        try:
            from app.services.gmail_service import get_recent_emails
            all_emails = get_recent_emails(max_results=10)
            emails = [e for e in all_emails if
                'azvickyfadzry02@gmail.com' not in e.get('from', '') and
                'noreply' not in e.get('from', '').lower() and
                'whatsapp' not in e.get('from', '').lower() and
                e.get('subject', '').strip() not in ['No Subject', '']
            ]

            msg_lower = message.lower()
            for e in emails:
                from_lower = e.get('from', '').lower()
                subject_lower = e.get('subject', '').lower()
                words = msg_lower.split()
                for word in words:
                    if len(word) > 3 and (word in from_lower or word in subject_lower):
                        target_email = e
                        break
                if target_email:
                    break

            if not target_email and emails:
                target_email = emails[0]

            if target_email:
                email_context = f"""Email yang harus dibalas:
from: {target_email.get('from', '')}
subject: {target_email.get('subject', '')}
isi: {target_email.get('body', target_email.get('snippet', ''))}
Gunakan field 'from' di atas sebagai reply_to."""

        except Exception as e:
            email_context = "Gagal membaca email."

    system_prompt = f"""Kamu adalah Orion AI, asisten eksekusi perintah bisnis.
{email_context}
Tugasmu adalah memahami perintah pengguna dan memberikan respons yang helpful.
Kamu bisa membantu:
- Membalas email
- Membalas pesan WhatsApp
- Membuat pesan bisnis
- Menjawab pertanyaan umum
PENTING:
1. Jawab HANYA dengan 1 JSON object saja, tanpa teks lain, tanpa backtick.
2. Langsung buatkan balasan email sesuai isi email di atas, jangan tanya-tanya.
3. Field reply_to WAJIB diisi dengan alamat email asli dari field "from" di atas.
4. Jangan pernah isi reply_to dengan placeholder apapun selain email asli.
Selalu jawab dalam format JSON:
{{
    "intent": "nama_aksi",
    "summary": "ringkasan aksi dalam bahasa Indonesia",
    "action": "detail teknis aksi",
    "needs_confirmation": true,
    "draft": "draft pesan/email yang siap dikirim dalam bahasa Indonesia yang sopan dan natural sesuai konteks email",
    "reply_to": "email asli pengirim",
    "subject": "Re: subject email asli"
}}
Untuk pesan WhatsApp, buat balasan yang sopan, natural, dan profesional dalam Bahasa Indonesia."""

    ai_response = await call_llm(system_prompt, message)
    parsed = parse_json_response(ai_response)

    if parsed:
        parsed["needs_confirmation"] = True
        reply_to = parsed.get("reply_to", "")
        if not reply_to or "@" not in reply_to:
            if target_email:
                from_field = target_email.get("from", "")
                match_email = re.search(r'<(.+?)>', from_field)
                if match_email:
                    parsed["reply_to"] = match_email.group(1)
                else:
                    parsed["reply_to"] = from_field

    return {
        "status": "success",
        "message": message,
        "response": json.dumps(parsed) if parsed else ai_response,
        "emails": emails,
        "parsed": parsed
    }


async def generate_briefing():
    from app.services.gmail_service import get_recent_emails

    all_emails = get_recent_emails(max_results=10)
    emails = [e for e in all_emails if
        'azvickyfadzry02@gmail.com' not in e.get('from', '') and
        'noreply' not in e.get('from', '').lower() and
        'whatsapp' not in e.get('from', '').lower() and
        e.get('subject', '').strip() not in ['No Subject', '']
    ]

    system_prompt = """Kamu adalah Orion AI. Analisa email berikut, lalu buat ringkasan prioritas.

Kategorikan setiap email menjadi:
- URGENT: Email dari manusia nyata yang butuh balasan
- BISA_NANTI: Email penting tapi tidak mendesak
- ARSIP: Newsletter otomatis, notifikasi sistem, promosi

Jawab HANYA dengan JSON murni tanpa backtick:
{
    "urgent": [{"from": "nama pengirim", "subject": "subjek email", "preview": "ringkasan singkat isi", "action": "apa yang harus dilakukan"}],
    "bisa_nanti": [{"from": "nama pengirim", "subject": "subjek email", "preview": "ringkasan singkat isi"}],
    "arsip": [{"from": "nama pengirim", "subject": "subjek email"}],
    "summary": "Ringkasan 1 kalimat kondisi inbox hari ini"
}"""

    ai_response = await call_llm(system_prompt, f"Email:\n{json.dumps(emails, indent=2)}")
    return parse_json_response(ai_response) or {}


async def extract_tasks():
    from app.services.gmail_service import get_recent_emails
    from app.services.database_service import get_wa_messages
    from app.services.calendar_service import add_calendar_event

    all_emails = get_recent_emails(max_results=10)
    emails = [e for e in all_emails if
        'azvickyfadzry02@gmail.com' not in e.get('from', '') and
        'noreply' not in e.get('from', '').lower() and
        e.get('subject', '').strip() not in ['No Subject', '']
    ]
    wa_messages = get_wa_messages(limit=10)

    system_prompt = """Kamu adalah Orion AI. Analisa email dan pesan WhatsApp berikut.
Deteksi semua task, meeting, deadline, permintaan file, dan follow up.

Jawab HANYA dengan JSON murni tanpa backtick:
{
    "tasks": [
        {
            "id": "unik_id_123",
            "type": "meeting/deadline/file/payment/followup",
            "title": "judul task singkat",
            "detail": "detail lengkap task",
            "from": "nama pengirim",
            "due": "ISO datetime jika ada contoh 2026-05-01T10:00:00, kosong jika tidak ada",
            "priority": "high/medium/low",
            "done": false
        }
    ],
    "summary": "ringkasan 1 kalimat jumlah task yang ditemukan"
}

Jika tidak ada task, kembalikan tasks sebagai array kosong."""

    ai_response = await call_llm(
        system_prompt,
        f"Email:\n{json.dumps(emails, indent=2)}\n\nWhatsApp:\n{json.dumps(wa_messages, indent=2)}"
    )
    parsed = parse_json_response(ai_response) or {"tasks": [], "summary": "Tidak ada task"}

    if parsed.get("tasks"):
        for task in parsed["tasks"]:
            if task.get("type") in ["meeting", "deadline"] and task.get("due"):
                try:
                    add_calendar_event(
                        title=task.get("title", ""),
                        description=f"Dari: {task.get('from', '')}\n{task.get('detail', '')}",
                        start_time=task.get("due", ""),
                        duration_hours=1
                    )
                except Exception:
                    pass

    return parsed


async def generate_wa_reply(message: str, business_context: str):
    return await call_llm(business_context, message)