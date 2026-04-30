import os
import requests
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