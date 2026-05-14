import os
import json
import re
from dotenv import load_dotenv
from app.services.ai_provider import call_llm, parse_json_response

load_dotenv()

# ── Detect casual/umum ────────────────────────────────────
def is_casual_message(message: str) -> bool:
    """
    Hanya deteksi pesan yang BENAR-BENAR casual/greeting.
    Tidak lagi pakai rule <= 4 kata karena terlalu agresif.
    """
    msg_lower = message.lower().strip()
    words = msg_lower.split()

    # Keyword bisnis — TIDAK boleh casual
    business_keywords = [
        'tagih', 'nagih', 'invoice', 'bayar', 'pembayaran',
        'email', 'balas', 'inbox', 'broadcast', 'kirim',
        'quotation', 'quote', 'penawaran', 'harga', 'berapa',
        'catat', 'ingat', 'simpan', 'follow', 'reminder',
        'meeting', 'notulen', 'laporan', 'file', 'dokumen',
        'sakit', 'demam', 'pusing', 'capek', 'lelah',
        'makan', 'tidur', 'kerja', 'bisnis', 'proyek',
        'customer', 'klien', 'supplier', 'investor',
        'jadwal', 'agenda', 'task', 'tugas', 'deadline',
        'masalah', 'problem', 'error', 'bug', 'eror',
        'buat', 'buatkan', 'generate', 'analisa', 'cek',
        'bantu', 'tolong', 'perlu', 'butuh', 'minta',
        'hari ini', 'besok', 'minggu', 'bulan', 'tahun',
        'saya', 'aku', 'gue', 'kita', 'kami', 'mereka',
    ]

    # Kalau ada keyword bisnis → BUKAN casual
    for kw in business_keywords:
        if kw in msg_lower:
            return False

    # Greeting murni — 1-3 kata saja
    pure_greetings = [
        'halo', 'hai', 'hello', 'hi', 'hey', 'hei',
        'pagi', 'siang', 'sore', 'malam',
        'ok', 'oke', 'okay', 'sip', 'siap',
        'makasih', 'thanks', 'thx',
        'mantap', 'keren', 'bagus', 'good',
        'yes', 'ya', 'yep', 'nope', 'no',
        'done', 'selesai', 'beres',
    ]

    # Kalau 1-2 kata dan cocok greeting → casual
    if len(words) <= 2:
        for greeting in pure_greetings:
            if msg_lower == greeting or msg_lower.startswith(greeting):
                return True
        return False

    # Kalau 3-4 kata, cek apakah pure greeting
    if len(words) <= 4:
        greeting_starters = [
            'halo orion', 'hai orion', 'hello orion', 'hi orion',
            'selamat pagi', 'selamat siang', 'selamat sore', 'selamat malam',
            'apa kabar', 'gimana kabar', 'terima kasih', 'makasih bro',
            'ok makasih', 'oke thanks', 'siap makasih',
        ]
        for starter in greeting_starters:
            if msg_lower.startswith(starter):
                return True
        return False

    # Lebih dari 4 kata → BUKAN casual, biarkan AI handle
    return False


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
        'daftar invoice', 'list tagihan', 'tagihan',
        'kirim tagihan', 'kirimkan tagihan', 'send invoice'
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
                format_amount, init_payment_db, send_invoice_wa_manual,
                get_invoice_by_number
            )
            init_payment_db()

            if not user_id or user_id == "default":
                reply = "⚠️ Kamu belum login. Silakan setup profil dulu di onboarding."
                return {
                    "status": "error",
                    "message": message,
                    "response": reply,
                    "emails": [],
                    "parsed": {
                        "intent": "payment",
                        "summary": reply,
                        "action": "error_no_user",
                        "needs_confirmation": False,
                        "draft": "",
                        "reply": reply,
                        "reply_to": "",
                        "subject": ""
                    }
                }

            msg_lower = message.lower()

            kirim_keywords = ['kirim tagihan', 'kirimkan tagihan', 'send invoice',
                               'kirim invoice', 'tagihkan sekarang', 'ingatkan sekarang']
            if any(kw in msg_lower for kw in kirim_keywords):
                inv_match = re.search(r'INV-[\w\d]+', message.upper())
                if inv_match:
                    inv_number = inv_match.group(0)
                    result = send_invoice_wa_manual(inv_number, user_id)
                    reply = f"📱 {result['message']}" if result['status'] == 'success' else f"❌ {result['message']}"
                else:
                    invoices = get_unpaid_invoices(user_id)
                    if not invoices:
                        reply = "📭 Tidak ada tagihan yang belum dibayar."
                    else:
                        reply = "📋 Pilih invoice mana yang ingin dikirim:\n\n"
                        for inv in invoices[:5]:
                            reply += f"• *{inv['invoice_number']}* — {inv['customer_name']} — {format_amount(inv['amount'])}\n"
                        reply += "\nKetik: 'kirim tagihan INV-xxx'"

                return {
                    "status": "success",
                    "message": message,
                    "response": reply,
                    "emails": [],
                    "parsed": {
                        "intent": "payment",
                        "summary": reply,
                        "action": "send_invoice_manual",
                        "needs_confirmation": False,
                        "draft": "",
                        "reply": reply,
                        "reply_to": "",
                        "subject": ""
                    }
                }

            if any(kw in msg_lower for kw in ['lunas', 'sudah bayar', 'konfirmasi bayar', 'bukti transfer']):
                reply = "✅ Untuk konfirmasi pembayaran, sebutkan nomor invoice nya!\n\nContoh: 'INV-20260509123456 sudah lunas'"
                inv_match = re.search(r'INV-[\w\d]+', message.upper())
                if inv_match:
                    inv_number = inv_match.group(0)
                    success = mark_invoice_paid(inv_number, user_id)
                    if success:
                        reply = f"✅ Invoice *{inv_number}* sudah ditandai LUNAS!\nReminder otomatis dihentikan."
                    else:
                        reply = f"❌ Invoice *{inv_number}* tidak ditemukan di akun kamu."

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

            if any(kw in msg_lower for kw in ['daftar invoice', 'list tagihan', 'semua tagihan', 'tagihan saya', 'daftar tagihan']):
                invoices = get_all_invoices(user_id)
                if not invoices:
                    reply = "📭 Kamu belum punya invoice apapun.\n\nBuat tagihan dengan:\n'tagih [nama] [nominal] [jatuh tempo] [nomor WA]'\n\nContoh: 'tagih Pak Andi 1 juta minggu depan 08123456789'"
                else:
                    unpaid = [i for i in invoices if i['status'] == 'unpaid']
                    paid = [i for i in invoices if i['status'] == 'paid']
                    reply = f"📋 *Daftar Invoice* ({len(invoices)} total)\n\n"
                    if unpaid:
                        reply += f"⏳ *Belum Lunas ({len(unpaid)}):*\n"
                        for inv in unpaid[:5]:
                            wa_info = " 📱" if inv.get('customer_phone') else " ⚠️ No WA"
                            reply += f"• {inv['invoice_number']} — {inv['customer_name']} — {format_amount(inv['amount'])} — {inv['due_date']}{wa_info}\n"
                    if paid:
                        reply += f"\n✅ *Sudah Lunas ({len(paid)}):*\n"
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

            invoice_info = await extract_invoice_from_command(message)
            customer_name = invoice_info.get("customer_name", "").strip()
            customer_phone = invoice_info.get("customer_phone", "").strip()
            customer_email = invoice_info.get("customer_email", "").strip()
            amount = invoice_info.get("amount", 0)
            description = invoice_info.get("description", "Tagihan")
            due_date = invoice_info.get("due_date", "")

            if not customer_name or amount <= 0:
                reply = "💰 Sebutkan detail tagihannya!\n\nContoh:\n• 'tagih Pak Budi 500rb besok 08123456789'\n• 'invoice Bu Sari 1.5 juta minggu depan'"
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
            reply += f"📄 *{invoice['invoice_number']}*\n"
            reply += f"👤 Customer: {customer_name}\n"
            reply += f"💰 Nominal: {format_amount(amount)}\n"
            reply += f"📅 Jatuh Tempo: {due_date}\n"
            reply += f"📝 Keterangan: {description}\n\n"

            if customer_phone:
                try:
                    from app.services.whatsapp_service import send_invoice_whatsapp
                    send_invoice_whatsapp(
                        phone=customer_phone,
                        customer_name=customer_name,
                        invoice_number=invoice['invoice_number'],
                        amount=amount,
                        due_date=due_date,
                        description=description,
                        is_reminder=False
                    )
                    reply += f"📱 WA tagihan langsung dikirim ke {customer_name}!\n"
                    reply += f"⏰ Reminder otomatis jam 09.00 saat jatuh tempo (maks 3x)"
                except Exception as wa_err:
                    print(f"[WA INVOICE ERROR] {wa_err}")
                    reply += f"⚠️ Invoice dibuat tapi WA gagal dikirim.\nCoba manual: 'kirim tagihan {invoice['invoice_number']}'"
            else:
                reply += f"💡 Tambahkan nomor WA customer biar Orion bisa auto kirim & reminder!\n"

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

        except ValueError as ve:
            reply = str(ve)
            return {
                "status": "error",
                "message": message,
                "response": reply,
                "emails": [],
                "parsed": {
                    "intent": "payment",
                    "summary": reply,
                    "action": "error_validation",
                    "needs_confirmation": False,
                    "draft": "",
                    "reply": reply,
                    "reply_to": "",
                    "subject": ""
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
                reply = f"✅ Tersimpan di Personal Brain!\n\n📝 *{entity_name}*\n{notes}"
                if follow_up_date:
                    reply += f"\n📅 Follow up: {follow_up_date}"

            elif action == "followup":
                save_brain_entry(
                    user_id=user_id,
                    entity_name=entity_name,
                    notes=f"Follow up dijadwalkan",
                    follow_up_date=follow_up_date
                )
                reply = f"⏰ Follow up untuk *{entity_name}* sudah dijadwalkan!"
                if follow_up_date:
                    reply += f"\nTanggal: {follow_up_date}"
                reply += "\n\nOrion akan mengingatkan kamu! Maksimal 2x follow up."

            elif action == "list":
                entries = get_all_brain_entries(user_id)
                if not entries:
                    reply = "📭 Personal Brain masih kosong. Coba catat sesuatu dulu!"
                else:
                    reply = f"🧠 *Personal Brain* ({len(entries)} entri):\n\n"
                    for e in entries[:10]:
                        follow_up_info = f" 📅 {e['follow_up_date']}" if e.get('follow_up_date') else ""
                        done_info = " ✅" if e.get('follow_up_done') else ""
                        reply += f"• *{e['name']}* ({e['type']}){follow_up_info}{done_info}\n"

            else:
                results = search_brain(user_id, query)
                if not results:
                    entry = get_brain_entry(user_id, query)
                    if entry:
                        results = [entry]

                if results:
                    r = results[0]
                    reply = f"🧠 *{r['name']}*\n\n{r['notes']}"
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

    # ── Handle Email + General AI ─────────────────────────
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
            print(f"[EMAIL LOAD ERROR] {e}")
            email_context = "Gagal membaca email."

    # ── General AI Handler — untuk semua perintah lain ──
    system_prompt = f"""Kamu adalah Orion AI, asisten eksekusi perintah bisnis yang sangat cerdas.
{email_context}

Tugasmu adalah memahami perintah pengguna dan memberikan respons yang helpful dan actionable.

PENTING:
1. Jawab HANYA dengan 1 JSON object saja, tanpa teks lain, tanpa backtick.
2. needs_confirmation hanya TRUE untuk perintah balas email.
3. Untuk pertanyaan umum atau percakapan → needs_confirmation: false, isi field "reply" dengan jawaban lengkap.
4. Field reply_to WAJIB diisi dengan email asli jika ada email konteks.
5. Kalau user curhat atau cerita sesuatu → respond dengan empati di field "reply".
6. Kalau user tanya sesuatu → jawab dengan informatif di field "reply".

Format JSON:
{{
    "intent": "nama_aksi",
    "summary": "ringkasan dalam bahasa Indonesia",
    "action": "detail aksi",
    "needs_confirmation": false,
    "draft": "draft email jika perlu dikirim, kosong jika tidak",
    "reply": "jawaban lengkap untuk user",
    "reply_to": "email asli pengirim jika ada",
    "subject": "subject email jika ada"
}}"""

    try:
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
        else:
            # Kalau JSON gagal parse → buat parsed manual dari raw response
            parsed = {
                "intent": "general",
                "summary": ai_response[:100],
                "action": "reply",
                "needs_confirmation": False,
                "draft": "",
                "reply": ai_response,
                "reply_to": "",
                "subject": ""
            }

        return {
            "status": "success",
            "message": message,
            "response": parsed.get("reply", ai_response),
            "emails": emails,
            "parsed": parsed
        }

    except Exception as e:
        print(f"[GENERAL AI ERROR] {e}")
        # Fallback response yang masih berguna
        reply = "Maaf, saya sedang mengalami gangguan. Coba ulangi perintah kamu ya! 🙏"
        return {
            "status": "error",
            "message": message,
            "response": reply,
            "emails": [],
            "parsed": {
                "intent": "error",
                "summary": reply,
                "action": "error",
                "needs_confirmation": False,
                "draft": "",
                "reply": reply,
                "reply_to": "",
                "subject": ""
            }
        }


async def generate_briefing(user_id: str = 'default'):
    try:
        from app.services.gmail_service import get_recent_emails
        all_emails = get_recent_emails(max_results=10, user_id=user_id)
        emails = [e for e in all_emails if
            'azvickyfadzry02@gmail.com' not in e.get('from', '') and
            'noreply' not in e.get('from', '').lower() and
            'whatsapp' not in e.get('from', '').lower() and
            e.get('subject', '').strip() not in ['No Subject', '']
        ]
    except Exception as e:
        print(f"[BRIEFING EMAIL ERROR] {e}")
        emails = []

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

    try:
        ai_response = await call_llm(system_prompt, f"Email:\n{json.dumps(emails, indent=2)}")
        return parse_json_response(ai_response) or {
            "urgent": [], "bisa_nanti": [], "arsip": [],
            "summary": "Tidak dapat menganalisa email saat ini."
        }
    except Exception as e:
        print(f"[BRIEFING AI ERROR] {e}")
        return {"urgent": [], "bisa_nanti": [], "arsip": [],
                "summary": "Email tidak dapat dimuat saat ini."}


async def extract_tasks(user_id: str = 'default'):
    try:
        from app.services.gmail_service import get_recent_emails
        all_emails = get_recent_emails(max_results=10, user_id=user_id)
        emails = [e for e in all_emails if
            'noreply' not in e.get('from', '').lower() and
            e.get('subject', '').strip() not in ['No Subject', '']
        ]
    except Exception as e:
        print(f"[TASKS EMAIL ERROR] {e}")
        emails = []

    try:
        from app.services.database_service import get_wa_messages
        wa_messages = get_wa_messages(limit=10)
    except Exception as e:
        print(f"[TASKS WA ERROR] {e}")
        wa_messages = []

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

    try:
        ai_response = await call_llm(
            system_prompt,
            f"Email:\n{json.dumps(emails, indent=2)}\n\nWhatsApp:\n{json.dumps(wa_messages, indent=2)}"
        )
        parsed = parse_json_response(ai_response) or {"tasks": [], "summary": "Tidak ada task"}
    except Exception as e:
        print(f"[TASKS AI ERROR] {e}")
        return {"tasks": [], "summary": "Tasks tidak dapat dimuat saat ini."}

    if parsed.get("tasks"):
        for task in parsed["tasks"]:
            if task.get("type") in ["meeting", "deadline"] and task.get("due"):
                try:
                    from app.services.calendar_service import add_calendar_event
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
    """Generate WA reply — Sales AI yang sangat pintar dan menjual"""

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
            return f"Halo {customer_name}! 😊 Makasih udah nanya ya!\n\nKami udah siapkan penawaran spesial buat kamu. Quotation *{quote['quote_number']}* lagi diproses dan akan segera kami kirimkan.\n\nAda yang mau ditanyain lagi? Kami siap bantu! 🙏"
        except Exception as e:
            print(f"[QUOTE ERROR] {e}")

    system_prompt = f"""Kamu adalah Sales AI kelas dunia untuk bisnis Indonesia — kombinasi dari sales expert berpengalaman 20 tahun, psikolog konsumen, dan customer service bintang 5.

{business_context}

IDENTITAS KAMU:
- Nama: Asisten dari bisnis ini
- Karakter: Hangat, cerdas, natural, seperti sahabat yang juga expert
- Bahasa: Indonesia santai tapi profesional, tidak formal kaku
- Gaya: Conversational, engaging, selalu ada energi positif

FRAMEWORK SALES:
1. RAPPORT — sapa dengan nama kalau tahu, match energy customer
2. NEED DISCOVERY — gali kebutuhan dengan natural
3. VALUE — highlight manfaat, bukan fitur teknis
4. OBJECTION HANDLING — empati dulu, baru solusi
5. CLOSING — pandu langkah selanjutnya dengan jelas
6. FOLLOW UP — tidak pushy, jaga hubungan

ATURAN:
- MAKSIMAL 3-4 kalimat per balasan
- JANGAN kaku seperti robot
- SELALU akhiri dengan pertanyaan atau CTA natural
- Emoji 1-2 per pesan, tidak berlebihan

Balas pesan customer berikut:"""

    try:
        return await call_llm(system_prompt, message)
    except Exception as e:
        print(f"[WA REPLY ERROR] {e}")
        return "Terima kasih atas pesan Anda! Kami akan segera membalas. 😊"

async def auto_extract_invoices_from_gmail(user_id: str = "default") -> dict:
    try:
        from app.services.gmail_service import get_recent_emails
        emails = get_recent_emails(max_results=20, user_id=user_id)
        if not emails:
            return {"status": "no_emails", "extracted": 0}
        invoice_keywords = ['invoice', 'faktur', 'purchase order', 'po number',
            'quotation', 'penawaran', 'tagihan', 'payment', 'pembayaran', 'harga', 'price']
        invoice_emails = []
        for email in emails:
            combined = f"{email.get('subject','')} {email.get('body','')} {email.get('snippet','')}".lower()
            if any(kw in combined for kw in invoice_keywords):
                invoice_emails.append(email)
        if not invoice_emails:
            return {"status": "no_invoices", "extracted": 0}
        system_prompt = """Kamu adalah sistem ekstraksi invoice untuk audit keuangan.
TUGAS: Ekstrak HANYA transaksi pembelian/penjualan yang NYATA dari email.

KRITERIA WAJIB — harus ada SEMUA ini untuk diekstrak:
1. Ada nama vendor/supplier yang spesifik
2. Ada angka harga yang jelas (bukan estimasi)
3. Ada deskripsi item/jasa yang spesifik
4. Email bukan promosi, newsletter, atau notifikasi sistem

JANGAN ekstrak:
- Email promosi Alibaba, LinkedIn, newsletter
- Email notifikasi sistem (Google, Binance, dll)
- Email tanpa angka harga yang spesifik
- Email yang hanya menyebut harga secara umum

Jawab JSON array:
[{"vendor_name":"nama vendor spesifik","item_description":"deskripsi item spesifik","unit_price":angka_harga,"quantity":jumlah,"total_amount":total,"invoice_number":"nomor invoice","category":"general/electronics/services/dll","source_email":"subject email"}]

Jika tidak ada transaksi yang memenuhi kriteria: []
Respond HANYA dengan JSON array, tidak ada teks lain."""
        email_content = "\n---\n".join([
            f"From: {e['from']}\nSubject: {e['subject']}\nContent: {e['body'][:500]}"
            for e in invoice_emails[:5]
        ])
        response = await call_llm(system_prompt, email_content)
        import json, re
        clean = response.replace('```json','').replace('```','').strip()
        # Cari array JSON dalam response
        match = re.search(r'\[.*\]', clean, re.DOTALL)
        if match:
            clean = match.group()
        try:
            transactions = json.loads(clean)
        except:
            transactions = []
        if not transactions:
            return {"status": "no_transactions_found", "extracted": 0}
        extracted_count = 0
        results = []
        for tx in transactions:
            try:
                if tx.get('vendor_name') and tx.get('unit_price', 0) > 0:
                    from app.services.zenith_service import analyze_price_guard
                    result = await analyze_price_guard(
                        user_id=user_id,
                        vendor_name=tx['vendor_name'],
                        item_description=tx.get('item_description', 'Unknown'),
                        unit_price=float(tx.get('unit_price', 0)),
                        quantity=float(tx.get('quantity', 1)),
                        category=tx.get('category', 'general'),
                        invoice_number=tx.get('invoice_number', ''),
                    )
                    results.append({
                        "vendor": tx['vendor_name'],
                        "item": tx['item_description'],
                        "risk_level": result.get('risk_level', 'UNKNOWN'),
                        "risk_score": result.get('risk_score', 0),
                        "source": tx.get('source_email', '')
                    })
                    extracted_count += 1
            except Exception as e:
                print(f"[AUTO EXTRACT] Error: {e}")
        return {"status": "success", "extracted": extracted_count, "results": results}
    except Exception as e:
        print(f"[AUTO EXTRACT ERROR] {e}")
        return {"status": "error", "message": str(e), "extracted": 0}


async def auto_extract_transactions_from_wa(user_id: str = "default") -> dict:
    """Auto extract transaksi dari pesan WA → Zenith Price Guard"""
    try:
        from app.services.database_service import get_wa_messages
        messages = get_wa_messages(limit=20, user_id=user_id)

        if not messages:
            return {"status": "no_messages", "extracted": 0}

        # Filter pesan yang kemungkinan berisi transaksi
        keywords = ['harga', 'price', 'invoice', 'faktur', 'penawaran',
                   'quotation', 'order', 'beli', 'jual', 'bayar', 'rp',
                   'rupiah', 'ribu', 'juta', 'dp', 'down payment']

        tx_messages = []
        for msg in messages:
            text = msg.get('message', '').lower()
            if any(kw in text for kw in keywords):
                tx_messages.append(msg)

        if not tx_messages:
            return {"status": "no_transactions", "extracted": 0}

        system_prompt = """Ekstrak data transaksi dari pesan WhatsApp bisnis.
HANYA ekstrak kalau ada harga spesifik dan nama item/jasa yang jelas.
JANGAN ekstrak pesan umum tanpa angka harga.

Jawab JSON array:
[{"vendor_name":"nama pengirim/vendor","item_description":"item/jasa","unit_price":angka,"quantity":1,"total_amount":angka,"category":"general","source_wa":"nomor WA"}]

Jika tidak ada: []
Respond HANYA dengan JSON."""

        wa_content = "\n---\n".join([
            f"From: {m.get('phone','')}\nMessage: {m.get('message','')[:300]}"
            for m in tx_messages[:10]
        ])

        response = await call_llm(system_prompt, wa_content)
        import json, re
        clean = response.replace('```json','').replace('```','').strip()
        match = re.search(r'\[.*\]', clean, re.DOTALL)
        if match:
            clean = match.group()
        try:
            transactions = json.loads(clean)
        except:
            transactions = []

        if not transactions:
            return {"status": "no_transactions_found", "extracted": 0}

        extracted_count = 0
        results = []
        for tx in transactions:
            try:
                if tx.get('vendor_name') and tx.get('unit_price', 0) > 0:
                    from app.services.zenith_service import analyze_price_guard
                    result = await analyze_price_guard(
                        user_id=user_id,
                        vendor_name=tx['vendor_name'],
                        item_description=tx.get('item_description', 'Unknown'),
                        unit_price=float(tx.get('unit_price', 0)),
                        quantity=float(tx.get('quantity', 1)),
                        category=tx.get('category', 'general'),
                    )
                    results.append({
                        "vendor": tx['vendor_name'],
                        "item": tx['item_description'],
                        "risk_level": result.get('risk_level', 'UNKNOWN'),
                        "risk_score": result.get('risk_score', 0),
                        "source_wa": tx.get('source_wa', '')
                    })
                    extracted_count += 1
            except Exception as e:
                print(f"[WA EXTRACT] Error: {e}")

        return {"status": "success", "extracted": extracted_count, "results": results}

    except Exception as e:
        print(f"[WA EXTRACT ERROR] {e}")
        return {"status": "error", "message": str(e), "extracted": 0}


async def auto_extract_transactions_from_wa(user_id: str = "default") -> dict:
    """Auto extract transaksi dari pesan WA → Zenith Price Guard"""
    try:
        from app.services.database_service import get_wa_messages
        messages = get_wa_messages(limit=20, user_id=user_id)

        if not messages:
            return {"status": "no_messages", "extracted": 0}

        # Filter pesan yang kemungkinan berisi transaksi
        keywords = ['harga', 'price', 'invoice', 'faktur', 'penawaran',
                   'quotation', 'order', 'beli', 'jual', 'bayar', 'rp',
                   'rupiah', 'ribu', 'juta', 'dp', 'down payment']

        tx_messages = []
        for msg in messages:
            text = msg.get('message', '').lower()
            if any(kw in text for kw in keywords):
                tx_messages.append(msg)

        if not tx_messages:
            return {"status": "no_transactions", "extracted": 0}

        system_prompt = """Ekstrak data transaksi dari pesan WhatsApp bisnis.
HANYA ekstrak kalau ada harga spesifik dan nama item/jasa yang jelas.
JANGAN ekstrak pesan umum tanpa angka harga.

Jawab JSON array:
[{"vendor_name":"nama pengirim/vendor","item_description":"item/jasa","unit_price":angka,"quantity":1,"total_amount":angka,"category":"general","source_wa":"nomor WA"}]

Jika tidak ada: []
Respond HANYA dengan JSON."""

        wa_content = "\n---\n".join([
            f"From: {m.get('phone','')}\nMessage: {m.get('message','')[:300]}"
            for m in tx_messages[:10]
        ])

        response = await call_llm(system_prompt, wa_content)
        import json, re
        clean = response.replace('```json','').replace('```','').strip()
        match = re.search(r'\[.*\]', clean, re.DOTALL)
        if match:
            clean = match.group()
        try:
            transactions = json.loads(clean)
        except:
            transactions = []

        if not transactions:
            return {"status": "no_transactions_found", "extracted": 0}

        extracted_count = 0
        results = []
        for tx in transactions:
            try:
                if tx.get('vendor_name') and tx.get('unit_price', 0) > 0:
                    from app.services.zenith_service import analyze_price_guard
                    result = await analyze_price_guard(
                        user_id=user_id,
                        vendor_name=tx['vendor_name'],
                        item_description=tx.get('item_description', 'Unknown'),
                        unit_price=float(tx.get('unit_price', 0)),
                        quantity=float(tx.get('quantity', 1)),
                        category=tx.get('category', 'general'),
                    )
                    results.append({
                        "vendor": tx['vendor_name'],
                        "item": tx['item_description'],
                        "risk_level": result.get('risk_level', 'UNKNOWN'),
                        "risk_score": result.get('risk_score', 0),
                        "source_wa": tx.get('source_wa', '')
                    })
                    extracted_count += 1
            except Exception as e:
                print(f"[WA EXTRACT] Error: {e}")

        return {"status": "success", "extracted": extracted_count, "results": results}

    except Exception as e:
        print(f"[WA EXTRACT ERROR] {e}")
        return {"status": "error", "message": str(e), "extracted": 0}
