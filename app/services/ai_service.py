import os
import json
import re
from dotenv import load_dotenv
from app.services.ai_provider import call_llm, parse_json_response

load_dotenv()

# ── Detect casual/umum (tidak perlu konfirmasi) ───────────
def is_casual_message(message: str) -> bool:
    casual_keywords = [
        'halo', 'hai', 'hello', 'hi', 'apa kabar', 'selamat',
        'pagi', 'siang', 'malam', 'sore', 'makasih', 'terima kasih',
        'ok', 'oke', 'siap', 'mantap', 'keren', 'bagus', 'good',
        'siapa kamu', 'kamu apa', 'orion itu', 'apa itu', 'gimana',
        'tolong', 'bantu', 'bisa', 'test', 'coba', 'help'
    ]
    msg_lower = message.lower().strip()
    if len(msg_lower.split()) <= 4:
        return True
    return any(kw in msg_lower for kw in casual_keywords)

# ── Detect request quotation ──────────────────────────────
def is_quote_request(message: str) -> bool:
    keywords = [
        'harga', 'price', 'quotation', 'quote', 'penawaran',
        'berapa', 'how much', 'cost', 'biaya', 'tarif',
        'minta harga', 'request harga', 'info harga', 'daftar harga'
    ]
    return any(kw in message.lower() for kw in keywords)

# ── Detect perintah kirim file ────────────────────────────
def is_send_file_command(message: str) -> bool:
    keywords = [
        'kirimkan file', 'kirim file', 'send file', 'kirimkan dokumen',
        'kirim dokumen', 'kirimkan laporan', 'kirim laporan',
        'forward file', 'kirimkan ke', 'tolong kirim', 'kirim data'
    ]
    return any(kw in message.lower() for kw in keywords)

# ── Extract info dari perintah kirim file ─────────────────
async def extract_send_file_info(message: str) -> dict:
    system_prompt = """Dari perintah berikut, ekstrak informasi dalam JSON:
{
    "file_name": "nama file yang ingin dikirim (tanpa ekstensi jika tidak disebutkan)",
    "recipient_name": "nama penerima",
    "recipient_email": "email penerima jika disebutkan, kosong jika tidak",
    "message_body": "pesan yang ingin disertakan dalam email",
    "subject": "subject email yang sesuai"
}
Respond HANYA dengan JSON."""
    try:
        response = await call_llm(system_prompt, message)
        clean = response.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except:
        return {
            "file_name": "",
            "recipient_name": "",
            "recipient_email": "",
            "message_body": "Terlampir file yang diminta.",
            "subject": "File dari Orion AI"
        }


async def process_command(message: str):
    email_keywords = ['email', 'balas', 'inbox', 'pesan masuk', 'surat']
    broadcast_keywords = ['broadcast', 'kirim semua', 'blast', 'semua customer', 'semua pelanggan']
    quote_keywords = ['quotation', 'quote', 'penawaran harga', 'buat quotation']
    file_keywords = ['kirimkan file', 'kirim file', 'kirimkan dokumen', 'kirim dokumen',
                     'kirimkan laporan', 'kirim laporan', 'kirimkan ke', 'kirim data']

    is_email_command = any(word in message.lower() for word in email_keywords)
    is_broadcast = any(word in message.lower() for word in broadcast_keywords)
    is_quote = any(word in message.lower() for word in quote_keywords)
    is_file_send = any(word in message.lower() for word in file_keywords)
    casual = is_casual_message(message)

    # ── Handle Casual — langsung jawab tanpa konfirmasi ──
    if casual and not is_email_command and not is_broadcast and not is_quote and not is_file_send:
        system_prompt = """Kamu adalah Orion AI, asisten bisnis yang cerdas dan ramah.
Jawab pesan berikut dengan natural, singkat, dan friendly dalam Bahasa Indonesia.
Kamu adalah AI assistant seperti Claude — langsung jawab tanpa format JSON.
Maksimal 2-3 kalimat saja."""
        try:
            reply = await call_llm(system_prompt, message)
            return {
                "status": "success",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "casual",
                    "summary": reply,
                    "action": "chat",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": ""
                }
            }
        except Exception as e:
            return {
                "status": "success",
                "message": message,
                "response": "Halo! Saya Orion AI, siap membantu kamu. 😊",
                "emails": [],
                "parsed": {
                    "intent": "casual",
                    "summary": "Halo! Saya Orion AI, siap membantu kamu. 😊",
                    "action": "chat",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": "Halo! Saya Orion AI, siap membantu kamu. 😊",
                    "reply_to": "",
                    "subject": ""
                }
            }

    # ── Handle Kirim File dari Drive ──
    if is_file_send:
        try:
            info = await extract_send_file_info(message)
            file_name = info.get("file_name", "")
            recipient_name = info.get("recipient_name", "")
            recipient_email = info.get("recipient_email", "")
            subject = info.get("subject", "File Terlampir")
            body = info.get("message_body", "Terlampir file yang diminta.")

            found_files = []
            download_path = ""
            actual_filename = ""

            if file_name:
                from app.services.gmail_service import search_drive_files
                found_files = search_drive_files(file_name, max_results=3)

            if not recipient_email and recipient_name:
                from app.services.gmail_service import search_contact_email
                from app.services.memory_service import get_all_customers
                customers = get_all_customers()
                for c in customers:
                    if recipient_name.lower() in (c.get("name", "") or "").lower():
                        recipient_email = c.get("phone", "")
                        break
                if not recipient_email or "@" not in recipient_email:
                    recipient_email = search_contact_email(recipient_name)

            if found_files and recipient_email and "@" in recipient_email:
                file_info = found_files[0]
                actual_filename = file_info["name"]
                from app.services.gmail_service import download_drive_file, send_email_with_attachment
                download_path = download_drive_file(file_info["id"], actual_filename)
                if download_path and os.path.exists(download_path):
                    send_result = send_email_with_attachment(
                        to=recipient_email,
                        subject=subject,
                        body=f"Halo {recipient_name},\n\n{body}\n\nSalam,\nOrion AI",
                        file_path=download_path,
                        filename=actual_filename
                    )
                    if send_result.get("status") == "sent":
                        summary = f"✅ File '{actual_filename}' berhasil dikirim ke {recipient_name} ({recipient_email})"
                    else:
                        summary = f"❌ Gagal mengirim file: {send_result.get('message', '')}"
                else:
                    summary = f"❌ Gagal download file '{actual_filename}' dari Drive"
            elif not found_files:
                summary = f"❌ File '{file_name}' tidak ditemukan di Google Drive"
            elif not recipient_email:
                summary = f"❌ Email {recipient_name} tidak ditemukan. Sebutkan emailnya secara langsung"
            else:
                summary = "❌ Gagal memproses perintah"

            return {
                "status": "success",
                "message": message,
                "response": summary,
                "parsed": {
                    "intent": "send_file",
                    "summary": summary,
                    "action": "send_file_email",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": summary,
                    "reply_to": recipient_email,
                    "subject": subject,
                    "file_name": actual_filename,
                    "found_files": [f["name"] for f in found_files],
                }
            }
        except Exception as e:
            summary = f"❌ Gagal kirim file: {str(e)}"
            return {
                "status": "error",
                "message": message,
                "response": summary,
                "parsed": {
                    "intent": "send_file",
                    "summary": summary,
                    "action": "error",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": summary,
                    "reply_to": "",
                    "subject": ""
                }
            }

    # ── Handle Broadcast ──
    if is_broadcast:
        # Hapus trigger words untuk ambil isi pesan
        pesan = message
        for trigger in broadcast_keywords:
            pesan = pesan.replace(trigger, '').strip()

        # Kalau pesan kosong atau terlalu pendek → tanya dulu
        if len(pesan) < 10:
            reply = "Siap! 📢 Pesan apa yang ingin kamu broadcast ke semua customer? Ketik pesannya sekarang."
            return {
                "status": "success",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "casual",
                    "summary": reply,
                    "action": "tanya_broadcast",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": ""
                }
            }

        # Kalau sudah ada pesan → langsung konfirmasi
        return {
            "status": "success",
            "message": message,
            "response": "Broadcast siap dikirim",
            "emails": [],
            "parsed": {
                "intent": "broadcast",
                "summary": f"Broadcast ke semua customer",
                "action": "broadcast",
                "needs_confirmation": True,
                "draft": pesan,
                "reply_to": "",
                "subject": ""
            }
        }

    # ── Handle Quote ──
    if is_quote:
        # Cek apakah ada detail customer
        pesan = message
        for trigger in quote_keywords:
            pesan = pesan.replace(trigger, '').strip()

        if len(pesan) < 5:
            reply = "Siap! 📋 Untuk siapa quotation ini dibuat? Dan produk/jasa apa yang ingin ditawarkan?"
            return {
                "status": "success",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "casual",
                    "summary": reply,
                    "action": "tanya_quotation",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": ""
                }
            }

        return {
            "status": "success",
            "message": message,
            "response": "Membuat quotation",
            "emails": [],
            "parsed": {
                "intent": "quotation",
                "summary": "Membuat quotation PDF",
                "action": "generate_quote",
                "needs_confirmation": True,
                "draft": pesan,
                "reply_to": "",
                "subject": ""
            }
        }

    # ── Handle Email ──
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

PENTING:
1. Jawab HANYA dengan 1 JSON object saja, tanpa teks lain, tanpa backtick.
2. needs_confirmation hanya TRUE untuk perintah balas email atau kirim pesan bisnis.
3. Untuk pertanyaan umum → needs_confirmation: false, isi field "reply" bukan "draft".
4. Field reply_to WAJIB diisi dengan alamat email asli jika ada email konteks.
5. Jangan pernah isi reply_to dengan placeholder.

Format JSON:
{{
    "intent": "nama_aksi",
    "summary": "ringkasan dalam bahasa Indonesia",
    "action": "detail aksi",
    "needs_confirmation": false,
    "draft": "draft email jika perlu dikirim, kosong jika tidak",
    "reply": "jawaban langsung untuk pertanyaan umum",
    "reply_to": "email asli pengirim jika ada",
    "subject": "subject email jika ada"
}}"""

    ai_response = await call_llm(system_prompt, message)
    parsed = parse_json_response(ai_response)

    if parsed:
        if is_email_command and parsed.get('draft') and parsed.get('reply_to'):
            parsed["needs_confirmation"] = True
        else:
            parsed["needs_confirmation"] = False

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


async def generate_wa_reply(message: str, business_context: str) -> str:
    """Generate WA reply — detect quotation request otomatis"""
    if is_quote_request(message):
        customer_name = "Customer"
        try:
            ctx = json.loads(business_context) if business_context.startswith("{") else {}
            customer_name = ctx.get("name", "Customer")
        except:
            pass

        try:
            from app.services.quote_service import generate_quote_from_request
            quote = await generate_quote_from_request(
                customer_name=customer_name,
                customer_phone="",
                request_text=message
            )
            return f"Terima kasih atas permintaan Anda! Kami telah menyiapkan penawaran harga untuk Anda. Quotation No: {quote['quote_number']} sedang diproses dan akan segera kami kirimkan. Ada yang ingin ditanyakan lebih lanjut? 😊"
        except Exception as e:
            print(f"[QUOTE ERROR] {e}")

    return await call_llm(business_context, message)