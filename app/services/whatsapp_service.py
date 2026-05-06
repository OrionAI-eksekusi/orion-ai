import os
import requests
import time
from dotenv import load_dotenv
from app.services.database_service import save_wa_message

load_dotenv()
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")

def send_whatsapp(phone: str, message: str):
    url = "https://api.fonnte.com/send"
    headers = {"Authorization": FONNTE_TOKEN}
    data = {"target": phone, "message": message}
    response = requests.post(url, headers=headers, data=data)
    return response.json()

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
        
        # Delay antar pesan biar tidak kena spam filter
        time.sleep(delay)

    return {
        "total": len(phones),
        "success": success,
        "failed": failed,
        "results": results
    }