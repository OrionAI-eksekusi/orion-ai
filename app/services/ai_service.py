import os
import json
import re
from dotenv import load_dotenv
from app.services.ai_provider import call_llm, parse_json_response

load_dotenv()

# ── Detect casual/umum ────────────────────────────────────
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

# ── Detect Personal Brain commands ───────────────────────
def is_brain_command(message: str) -> bool:
    keywords = [
        'catat', 'ingat', 'simpan', 'note', 'remember',
        'siapa', 'info tentang', 'ceritakan tentang',
        'follow up', 'followup', 'tindak lanjut',
        'ingatkan', 'remind', 'jadwalkan follow',
        'apa yang kamu tahu tentang', 'cari di memory',
        'daftar kontak', 'semua catatan', 'list kontak'
    ]
    return any(kw in message.lower() for kw in keywords)

# ── Detect Payment/Invoice commands ──────────────────────
def is_payment_command(message: str) -> bool:
    keywords = [
        'tagih', 'nagih', 'invoice', 'bayar', 'pembayaran',
        'reminder bayar', 'ingatkan bayar', 'belum bayar',
        'jatuh tempo', 'cicilan', 'tunggakan', 'lunas',
        'sudah bayar', 'konfirmasi bayar', 'bukti transfer',
        'daftar invoice', 'list tagihan', 'tagihan'
    ]
    return any(kw in message.lower() for kw in keywords)

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
    "file_name": "nama file yang ingin dikirim",
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

# ── Extract Brain info dari perintah ─────────────────────
async def extract_brain_info(message: str) -> dict:
    system_prompt = """Dari perintah berikut, ekstrak informasi untuk Personal Brain dalam JSON:
{
    "action": "save/query/list/followup",
    "entity_name": "nama orang/perusahaan/topik yang dimaksud",
    "entity_type": "contact/investor/customer/supplier/idea/note",
    "notes": "informasi yang ingin disimpan",
    "follow_up_date": "tanggal follow up format YYYY-MM-DD jika ada, kosong jika tidak",
    "query": "kata kunci pencarian jika action=query"
}

Contoh:
- "catat Pak Rudi investor dari Jakarta budget 2M" → action=save, entity_name=Pak Rudi
- "siapa Pak Rudi?" → action=query, query=Pak Rudi
- "follow up Pak Rudi besok" → action=followup, entity_name=Pak Rudi
- "daftar semua kontak" → action=list

Respond HANYA dengan JSON."""
    try:
        response = await call_llm(system_prompt, message)
        clean = response.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except:
        return {
            "action": "query",
            "entity_name": "",
            "entity_type": "contact",
            "notes": message,
            "follow_up_date": "",
            "query": message
        }


async def process_command(message: str, user_id: str = "default"):
    email_keywords = ['email', 'balas', 'inbox', 'pesan masuk', 'surat']
    broadcast_keywords = ['broadcast', 'kirim semua', 'blast', 'semua customer', 'semua pelanggan']
    quote_keywords = ['quotation', 'quote', 'penawaran harga', 'buat quotation']
    file_keywords = ['kirimkan file', 'kirim file', 'kirimkan dokumen', 'kirim dokumen',
                     'kirimkan laporan', 'kirim laporan', 'kirimkan ke', 'kirim data']

    is_email_command = any(word in message.lower() for word in email_keywords)
    is_broadcast = any(word in message.lower() for word in broadcast_keywords)
    is_quote = any(word in message.lower() for word in quote_keywords)
    is_file_send = any(word in message.lower() for word in file_keywords)
    is_brain = is_brain_command(message)
    is_payment = is_payment_command(message)
    casual = is_casual_message(message)

    # ── Handle Payment / Invoice ──────────────────────────
    if is_payment and not is_email_command:
        try:
            from app.services.payment_service import (
                create_invoice, get_all_invoices, get_unpaid_invoices,
                mark_invoice_paid, extract_invoice_from_command,
                format_amount, init_payment_db
            )
            init_payment_db()

            msg_lower = message.lower()

            # Cek apakah konfirmasi lunas
            if any(kw in msg_lower for kw in ['lunas', 'sudah bayar', 'konfirmasi bayar', 'bukti transfer']):
                reply = "✅ Terima kasih! Untuk konfirmasi pembayaran, sebutkan nomor invoice nya bro!\n\nContoh: 'INV-20260509123456 sudah lunas'"

                # Cek ada nomor invoice di pesan
                inv_match = re.search(r'INV-\d+', message.upper())
                if inv_match:
                    inv_number = inv_match.group(0)
                    success = mark_invoice_paid(inv_number, user_id)
                    if success:
                        reply = f"✅ Invoice **{inv_number}** sudah ditandai LUNAS!\nReminder otomatis dihentikan."
                    else:
                        reply = f"❌ Invoice **{inv_number}** tidak ditemukan."

                return {
                    "status": "success",
                    "message": message,
                    "response": reply,
                    "emails": [],
                    "parsed": {
                        "intent": "payment",
                        "summary": reply,
                        "action": "mark_paid",
                        "needs_confirmation": False,
                        "draft": "",
                        "reply": reply,
                        "reply_to": "",
                        "subject": ""
                    }
                }

            # Cek daftar invoice
            if any(kw in msg_lower for kw in ['daftar invoice', 'list tagihan', 'semua tagihan', 'tagihan saya']):
                invoices = get_all_invoices(user_id)
                if not invoices:
                    reply = "📭 Belum ada invoice. Buat dulu dengan: 'tagih [nama] [nominal] [jatuh tempo]'"
                else:
                    unpaid = [i for i in invoices if i['status'] == 'unpaid']
                    paid = [i for i in invoices if i['status'] == 'paid']
                    reply = f"📋 **Daftar Invoice** ({len(invoices)} total)\n\n"
                    if unpaid:
                        reply += f"⏳ **Belum Lunas ({len(unpaid)}):**\n"
                        for inv in unpaid[:5]:
                            reply += f"• {inv['invoice_number']} — {inv['customer_name']} — {format_amount(inv['amount'])} — Jatuh tempo: {inv['due_date']}\n"
                    if paid:
                        reply += f"\n✅ **Sudah Lunas ({len(paid)}):**\n"
                        for inv in paid[:3]:
                            reply += f"• {inv['invoice_number']} — {inv['customer_name']} — {format_amount(inv['amount'])}\n"

                return {
                    "status": "success",
                    "message": message,
                    "response": reply,
                    "emails": [],
                    "parsed": {
                        "intent": "payment",
                        "summary": reply,
                        "action": "list_invoices",
                        "needs_confirmation": False,
                        "draft": "",
                        "reply": reply,
                        "reply_to": "",
                        "subject": ""
                    }
                }

            # Buat invoice baru
            invoice_info = await extract_invoice_from_command(message)
            customer_name = invoice_info.get("customer_name", "")
            customer_phone = invoice_info.get("customer_phone", "")
            customer_email = invoice_info.get("customer_email", "")
            amount = invoice_info.get("amount", 0)
            description = invoice_info.get("description", "Tagihan")
            due_date = invoice_info.get("due_date", "")

            if not customer_name or amount <= 0:
                reply = "Siap! 💰 Sebutkan detail tagihannya bro!\n\nContoh:\n'tagih Pak Budi 500rb besok'\n'invoice Bu Sari 1.5 juta minggu depan 081234567'"
                return {
                    "status": "success",
                    "message": message,
                    "response": reply,
                    "emails": [],
                    "parsed": {
                        "intent": "payment",
                        "summary": reply,
                        "action": "tanya_invoice",
                        "needs_confirmation": False,
                        "draft": "",
                        "reply": reply,
                        "reply_to": "",
                        "subject": ""
                    }
                }

            # Buat invoice
            invoice = create_invoice(
                user_id=user_id,
                customer_name=customer_name,
                amount=amount,
                due_date=due_date,
                description=description,
                customer_phone=customer_phone,
                customer_email=customer_email
            )

            reply = f"✅ Invoice berhasil dibuat!\n\n"
            reply += f"📄 **{invoice['invoice_number']}**\n"
            reply += f"👤 Customer: {customer_name}\n"
            reply += f"💰 Nominal: {format_amount(amount)}\n"
            reply += f"📅 Jatuh Tempo: {due_date}\n"
            reply += f"📝 Keterangan: {description}\n\n"

            if customer_phone:
                reply += f"📱 Orion akan auto WA reminder ke {customer_phone} saat jatuh tempo!\n"
                reply += f"⚡ Maksimal 3x reminder, lalu berhenti otomatis."
            else:
                reply += f"💡 Tambahkan nomor WA customer biar Orion bisa auto reminder!"

            return {
                "status": "success",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "payment",
                    "summary": reply,
                    "action": "create_invoice",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": "",
                    "invoice": invoice
                }
            }

        except Exception as e:
            print(f"[PAYMENT ERROR] {e}")
            reply = f"❌ Gagal proses payment: {str(e)}"
            return {
                "status": "error",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "payment",
                    "summary": reply,
                    "action": "error",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": ""
                }
            }

    # ── Handle Personal Brain ─────────────────────────────
    if is_brain and not is_email_command and not is_broadcast:
        try:
            from app.services.memory_service import (
                save_brain_entry, get_brain_entry,
                get_all_brain_entries, search_brain
            )

            brain_info = await extract_brain_info(message)
            action = brain_info.get("action", "query")
            entity_name = brain_info.get("entity_name", "")
            notes = brain_info.get("notes", "")
            entity_type = brain_info.get("entity_type", "contact")
            follow_up_date = brain_info.get("follow_up_date", "")
            query = brain_info.get("query", message)

            if action == "save":
                save_brain_entry(
                    user_id=user_id,
                    entity_name=entity_name,
                    notes=notes,
                    entity_type=entity_type,
                    follow_up_date=follow_up_date
                )
                reply = f"✅ Tersimpan di Personal Brain!\n\n📝 **{entity_name}**\n{notes}"
                if follow_up_date:
                    reply += f"\n📅 Follow up: {follow_up_date}"

            elif action == "followup":
                save_brain_entry(
                    user_id=user_id,
                    entity_name=entity_name,
                    notes=f"Follow up dijadwalkan",
                    follow_up_date=follow_up_date
                )
                reply = f"⏰ Follow up untuk **{entity_name}** sudah dijadwalkan!"
                if follow_up_date:
                    reply += f"\nTanggal: {follow_up_date}"
                reply += "\n\nOrion akan mengingatkan kamu! Maksimal 2x follow up."

            elif action == "list":
                entries = get_all_brain_entries(user_id)
                if not entries:
                    reply = "📭 Personal Brain masih kosong. Coba catat sesuatu dulu!"
                else:
                    reply = f"🧠 **Personal Brain** ({len(entries)} entri):\n\n"
                    for e in entries[:10]:
                        follow_up_info = f" 📅 {e['follow_up_date']}" if e.get('follow_up_date') else ""
                        done_info = " ✅" if e.get('follow_up_done') else ""
                        reply += f"• **{e['name']}** ({e['type']}){follow_up_info}{done_info}\n"

            else:
                results = search_brain(user_id, query)
                if not results:
                    entry = get_brain_entry(user_id, query)
                    if entry:
                        results = [entry]

                if results:
                    r = results[0]
                    reply = f"🧠 **{r['name']}**\n\n{r['notes']}"
                    if r.get('follow_up_date') and not r.get('follow_up_done'):
                        reply += f"\n\n📅 Follow up: {r['follow_up_date']}"
                else:
                    reply = f"🔍 Tidak ditemukan info tentang '{query}' di Personal Brain.\n\nCoba catat dulu dengan: 'catat [nama] [informasi]'"

            return {
                "status": "success",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "brain",
                    "summary": reply,
                    "action": action,
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": ""
                }
            }

        except Exception as e:
            print(f"[BRAIN ERROR] {e}")
            reply = f"❌ Gagal akses Personal Brain: {str(e)}"
            return {
                "status": "error",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "brain",
                    "summary": reply,
                    "action": "error",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": ""
                }
            }

    # ── Handle Casual ─────────────────────────────────────
    if casual and not is_email_command and not is_broadcast and not is_quote and not is_file_send:
        system_prompt = """Kamu adalah Orion AI, asisten bisnis yang cerdas dan ramah.
Jawab pesan berikut dengan natural, singkat, dan friendly dalam Bahasa Indonesia.
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

    # ── Handle Kirim File dari Drive ──────────────────────
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

    # ── Handle Broadcast ──────────────────────────────────
    if is_broadcast:
        pesan = message
        for trigger in broadcast_keywords:
            pesan = pesan.replace(trigger, '').strip()

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

        return {
            "status": "success",
            "message": message,
            "response": "Broadcast siap dikirim",
            "emails": [],
            "parsed": {
                "intent": "broadcast",
                "summary": "Broadcast ke semua customer",
                "action": "broadcast",
                "needs_confirmation": True,
                "draft": pesan,
                "reply_to": "",
                "subject": ""
            }
        }

    # ── Handle Quote ──────────────────────────────────────
    if is_quote:
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

    # ── Handle Email ──────────────────────────────────────
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
2. needs_confirmation hanya TRUE untuk perintah balas email.
3. Untuk pertanyaan umum → needs_confirmation: false, isi field "reply".
4. Field reply_to WAJIB diisi dengan email asli jika ada email konteks.

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