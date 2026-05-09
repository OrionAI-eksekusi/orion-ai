import os
import requests
import time
from dotenv import load_dotenv
from app.services.database_service import save_wa_message

load_dotenv()

FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")
WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "http://localhost:3000")


def send_whatsapp(phone: str, message: str):
    """Kirim WA via Fonnte — untuk broadcast"""
    url = "https://api.fonnte.com/send"
    headers = {"Authorization": FONNTE_TOKEN}
    data = {"target": phone, "message": message}
    response = requests.post(url, headers=headers, data=data)
    return response.json()


def send_whatsapp_baileys(phone: str, message: str) -> dict:
    """
    Kirim WA via Baileys (worker Railway) — untuk tagihan & reminder.
    Pakai koneksi WA yang sudah di-scan user di Orion.
    Tidak perlu Fonnte sama sekali.
    """
    try:
        phone_clean = phone.strip().replace(" ", "").replace("-", "")
        if phone_clean.startswith("0"):
            phone_clean = "62" + phone_clean[1:]
        elif not phone_clean.startswith("62"):
            phone_clean = "62" + phone_clean

        response = requests.post(
            f"{WA_GATEWAY_URL}/send-message",
            json={"phone": phone_clean, "message": message},
            timeout=15
        )
        result = response.json()
        return result
    except Exception as e:
        print(f"[BAILEYS SEND ERROR] {e}")
        return {"status": False, "error": str(e)}


def send_invoice_whatsapp(
    phone: str,
    customer_name: str,
    invoice_number: str,
    amount: float,
    due_date: str,
    description: str = "",
    is_reminder: bool = False,
    reminder_count: int = 1
) -> dict:
    """
    Kirim WA tagihan ke customer via Baileys.
    is_reminder=False → pesan pertama saat invoice dibuat
    is_reminder=True  → pesan reminder saat jatuh tempo
    """
    amount_str = f"Rp {amount:,.0f}".replace(",", ".")

    if not is_reminder:
        message = f"""Halo {customer_name}! 👋

Kami ingin menginformasikan tagihan berikut:

📄 *Invoice:* {invoice_number}
💰 *Nominal:* {amount_str}
📅 *Jatuh Tempo:* {due_date}
📝 *Keterangan:* {description if description else 'Tagihan jasa/produk'}

Mohon pembayaran sebelum tanggal jatuh tempo ya.
Konfirmasi pembayaran bisa langsung balas pesan ini. 🙏

_Terima kasih atas kepercayaan Anda!_"""

    else:
        if reminder_count == 1:
            message = f"""Halo {customer_name},

Kami mengingatkan bahwa tagihan berikut sudah jatuh tempo:

📄 *Invoice:* {invoice_number}
💰 *Nominal:* {amount_str}
📅 *Jatuh Tempo:* {due_date}

Mohon segera lakukan pembayaran.
Konfirmasi langsung balas pesan ini ya! 🙏"""

        elif reminder_count == 2:
            message = f"""Halo {customer_name},

Ini adalah pengingat ke-2 untuk tagihan yang belum dibayar:

📄 *Invoice:* {invoice_number}
💰 *Nominal:* {amount_str}
📅 *Jatuh Tempo:* {due_date}

Harap segera diselesaikan. Terima kasih. 🙏"""

        else:
            message = f"""Halo {customer_name},

Ini adalah pengingat terakhir untuk tagihan:

📄 *Invoice:* {invoice_number}
💰 *Nominal:* {amount_str}
📅 *Jatuh Tempo:* {due_date}

Mohon segera hubungi kami jika ada kendala pembayaran.
Terima kasih. 🙏"""

    return send_whatsapp_baileys(phone, message)


def receive_whatsapp_message(data: dict):
    phone = data.get("phone", "") or data.get("sender", "")
    message = data.get("message", "")
    if phone and message:
        save_wa_message(phone, message)
    return {"phone": phone, "message": message}


def broadcast_whatsapp(phones: list, message: str, delay: float = 2.0):
    """Kirim pesan broadcast ke banyak nomor dengan delay antar pesan"""
    results = []
    success = 0
    failed = 0

    for phone in phones:
        try:
            result = send_whatsapp(phone, message)
            if result.get("status") == True or result.get("status") == "true":
                success += 1
                results.append({"phone": phone, "status": "success"})
            else:
                failed += 1
                results.append({"phone": phone, "status": "failed", "reason": str(result)})
        except Exception as e:
            failed += 1
            results.append({"phone": phone, "status": "error", "reason": str(e)})
        time.sleep(delay)

    return {
        "total": len(phones),
        "success": success,
        "failed": failed,
        "results": results
    }