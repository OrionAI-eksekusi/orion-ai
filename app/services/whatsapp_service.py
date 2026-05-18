"""
APEX WhatsApp Service
Fixed: hardcoded user_id, blocking requests → httpx async, user_id propagation
"""
import os
import base64
import asyncio
import httpx
from app.services.database_service import save_wa_message

WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "http://localhost:3000")
FONNTE_TOKEN   = os.getenv("FONNTE_TOKEN", "")


# ─── UTILS ────────────────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0"):
        return "62" + phone[1:]
    if not phone.startswith("62"):
        return "62" + phone
    return phone


# ─── SEND TEXT ────────────────────────────────────────────────────────────────

def send_whatsapp_baileys(phone: str, message: str, user_id: str = "") -> dict:
    """Kirim WA teks via Baileys — sync wrapper"""
    try:
        phone_clean = _normalize_phone(phone)
        response = httpx.post(
            f"{WA_GATEWAY_URL}/send-message",
            json={"phone": phone_clean, "message": message, "user_id": user_id},
            timeout=15
        )
        return response.json()
    except Exception as e:
        print(f"[WA SEND ERROR] {e}")
        return {"status": False, "error": str(e)}


async def send_whatsapp_async(phone: str, message: str, user_id: str = "") -> dict:
    """Kirim WA teks via Baileys — async"""
    try:
        phone_clean = _normalize_phone(phone)
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{WA_GATEWAY_URL}/send-message",
                json={"phone": phone_clean, "message": message, "user_id": user_id}
            )
            return response.json()
    except Exception as e:
        print(f"[WA ASYNC SEND ERROR] {e}")
        return {"status": False, "error": str(e)}


# ─── SEND FILE ────────────────────────────────────────────────────────────────

def send_file_whatsapp_baileys(
    phone: str, file_path: str, filename: str,
    caption: str = "", user_id: str = ""
) -> dict:
    """Kirim file PDF via Baileys"""
    try:
        phone_clean = _normalize_phone(phone)
        with open(file_path, "rb") as f:
            file_base64 = base64.b64encode(f.read()).decode("utf-8")
        response = httpx.post(
            f"{WA_GATEWAY_URL}/send-file",
            json={
                "phone":       phone_clean,
                "file_base64": file_base64,
                "filename":    filename,
                "caption":     caption,
                "user_id":     user_id,
            },
            timeout=30
        )
        return response.json()
    except Exception as e:
        print(f"[WA FILE SEND ERROR] {e}")
        return {"status": False, "error": str(e)}


# ─── INVOICE WA ───────────────────────────────────────────────────────────────

def send_invoice_whatsapp(
    phone: str, customer_name: str, invoice_number: str,
    amount: float, due_date: str, description: str = "",
    is_reminder: bool = False, reminder_count: int = 1,
    user_id: str = ""
) -> dict:
    """Kirim WA tagihan ke customer"""
    amount_str = f"Rp {amount:,.0f}".replace(",", ".")

    if not is_reminder:
        message = (
            f"Halo {customer_name}! 👋\n\n"
            f"Kami ingin menginformasikan tagihan berikut:\n\n"
            f"📄 *Invoice:* {invoice_number}\n"
            f"💰 *Nominal:* {amount_str}\n"
            f"📅 *Jatuh Tempo:* {due_date}\n"
            f"📝 *Keterangan:* {description or 'Tagihan jasa/produk'}\n\n"
            f"Mohon pembayaran sebelum tanggal jatuh tempo ya.\n"
            f"Konfirmasi pembayaran bisa langsung balas pesan ini. 🙏\n\n"
            f"_Terima kasih atas kepercayaan Anda!_"
        )
    elif reminder_count == 1:
        message = (
            f"Halo {customer_name},\n\n"
            f"Kami mengingatkan bahwa tagihan berikut sudah jatuh tempo:\n\n"
            f"📄 *Invoice:* {invoice_number}\n"
            f"💰 *Nominal:* {amount_str}\n"
            f"📅 *Jatuh Tempo:* {due_date}\n\n"
            f"Mohon segera lakukan pembayaran.\n"
            f"Konfirmasi langsung balas pesan ini ya! 🙏"
        )
    elif reminder_count == 2:
        message = (
            f"Halo {customer_name},\n\n"
            f"Ini pengingat ke-2 untuk tagihan yang belum dibayar:\n\n"
            f"📄 *Invoice:* {invoice_number}\n"
            f"💰 *Nominal:* {amount_str}\n"
            f"📅 *Jatuh Tempo:* {due_date}\n\n"
            f"Harap segera diselesaikan. Terima kasih. 🙏"
        )
    else:
        message = (
            f"Halo {customer_name},\n\n"
            f"Ini pengingat terakhir untuk tagihan:\n\n"
            f"📄 *Invoice:* {invoice_number}\n"
            f"💰 *Nominal:* {amount_str}\n"
            f"📅 *Jatuh Tempo:* {due_date}\n\n"
            f"Mohon segera hubungi kami jika ada kendala pembayaran.\n"
            f"Terima kasih. 🙏"
        )

    return send_whatsapp_baileys(phone, message, user_id=user_id)


# ─── RECEIVE ──────────────────────────────────────────────────────────────────

def receive_whatsapp_message(data: dict) -> dict:
    """Parse payload WA masuk dan simpan ke DB"""
    phone   = data.get("phone", "") or data.get("sender", "")
    message = data.get("message", "")
    user_id = data.get("user_id", "")

    if phone and message and user_id:
        save_wa_message(phone, message, user_id=user_id)

    return {"phone": phone, "message": message}


# ─── BROADCAST ────────────────────────────────────────────────────────────────

async def broadcast_whatsapp(phones: list, message: str, user_id: str = "", delay: float = 2.0) -> dict:
    """Broadcast WA ke banyak nomor — async dengan delay"""
    results = []
    success = 0
    failed  = 0

    for phone in phones:
        try:
            result = await send_whatsapp_async(phone, message, user_id=user_id)
            if result.get("status") in [True, "true", "success"]:
                success += 1
                results.append({"phone": phone, "status": "success"})
            else:
                failed += 1
                results.append({"phone": phone, "status": "failed", "reason": str(result)})
        except Exception as e:
            failed += 1
            results.append({"phone": phone, "status": "error", "reason": str(e)})
        await asyncio.sleep(delay)

    return {"total": len(phones), "success": success, "failed": failed, "results": results}


# ─── LEGACY (Fonnte — masih dipakai untuk broadcast lama) ─────────────────────

def send_whatsapp(phone: str, message: str) -> dict:
    """Kirim WA via Fonnte — legacy broadcast"""
    try:
        response = httpx.post(
            "https://api.fonnte.com/send",
            headers={"Authorization": FONNTE_TOKEN},
            data={"target": phone, "message": message},
            timeout=15
        )
        return response.json()
    except Exception as e:
        print(f"[FONNTE SEND ERROR] {e}")
        return {"status": False, "error": str(e)}
