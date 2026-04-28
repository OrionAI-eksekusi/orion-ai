import os
import json
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

async def process_command(message: str):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

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

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": f"""Kamu adalah Orion AI, asisten eksekusi perintah bisnis.
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
            },
            {
                "role": "user",
                "content": message
            }
        ]
    )

    ai_response = response.choices[0].message.content

    try:
        clean = ai_response.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(clean)
    except:
        match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        parsed = json.loads(match.group()) if match else None

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
    from app.services.database_service import get_wa_messages

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    all_emails = get_recent_emails(max_results=10)
    emails = [e for e in all_emails if
        'azvickyfadzry02@gmail.com' not in e.get('from', '') and
        'noreply' not in e.get('from', '').lower() and
        'whatsapp' not in e.get('from', '').lower() and
        e.get('subject', '').strip() not in ['No Subject', '']
    ]
    wa_messages = get_wa_messages(limit=10)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Kamu adalah Orion AI. Analisa email dan pesan WhatsApp berikut, lalu buat ringkasan prioritas.

Kategorikan setiap item menjadi:
- URGENT: Butuh respons segera (client, deal, meeting, deadline, permintaan penting)
- BISA_NANTI: Penting tapi tidak mendesak
- ARSIP: Newsletter, notifikasi otomatis, promosi, iklan yang tidak perlu dibalas

Jawab HANYA dengan JSON murni tanpa backtick:
{
    "urgent": [{"from": "nama pengirim", "subject": "subjek", "preview": "ringkasan singkat isi", "action": "apa yang harus dilakukan"}],
    "bisa_nanti": [{"from": "nama pengirim", "subject": "subjek", "preview": "ringkasan singkat isi"}],
    "arsip": [{"from": "nama pengirim", "subject": "subjek"}],
    "summary": "Ringkasan 1 kalimat kondisi inbox hari ini"
}"""
            },
            {
                "role": "user",
                "content": f"Email:\n{json.dumps(emails, indent=2)}\n\nWhatsApp:\n{json.dumps(wa_messages, indent=2)}"
            }
        ]
    )

    ai_response = response.choices[0].message.content

    try:
        clean = ai_response.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(clean)
    except:
        match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}

    return parsed


async def extract_tasks():
    from app.services.gmail_service import get_recent_emails
    from app.services.database_service import get_wa_messages

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    all_emails = get_recent_emails(max_results=10)
    emails = [e for e in all_emails if
        'azvickyfadzry02@gmail.com' not in e.get('from', '') and
        'noreply' not in e.get('from', '').lower() and
        e.get('subject', '').strip() not in ['No Subject', '']
    ]
    wa_messages = get_wa_messages(limit=10)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Kamu adalah Orion AI. Analisa email dan pesan WhatsApp berikut.
Deteksi semua task, meeting, deadline, permintaan file, dan follow up yang perlu dilakukan.

Jawab HANYA dengan JSON murni tanpa backtick:
{
    "tasks": [
        {
            "id": "unik_id_123",
            "type": "meeting/deadline/file/payment/followup",
            "title": "judul task singkat",
            "detail": "detail lengkap task",
            "from": "nama pengirim",
            "due": "tanggal/waktu jika ada, kosong jika tidak ada",
            "priority": "high/medium/low",
            "done": false
        }
    ],
    "summary": "ringkasan 1 kalimat jumlah task yang ditemukan"
}

Jika tidak ada task, kembalikan tasks sebagai array kosong."""
            },
            {
                "role": "user",
                "content": f"Email:\n{json.dumps(emails, indent=2)}\n\nWhatsApp:\n{json.dumps(wa_messages, indent=2)}"
            }
        ]
    )

    ai_response = response.choices[0].message.content

    try:
        clean = ai_response.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(clean)
    except:
        match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        parsed = json.loads(match.group()) if match else {"tasks": [], "summary": "Tidak ada task"}

    return parsed


async def generate_wa_reply(message: str, business_context: str):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": business_context
            },
            {
                "role": "user",
                "content": message
            }
        ]
    )

    return response.choices[0].message.content