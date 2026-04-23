import os
import requests
from dotenv import load_dotenv

load_dotenv()

FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")

def send_whatsapp(phone: str, message: str):
    url = "https://api.fonnte.com/send"
    headers = {"Authorization": FONNTE_TOKEN}
    data = {
        "target": phone,
        "message": message,
    }
    response = requests.post(url, headers=headers, data=data)
    return response.json()

def receive_whatsapp_message(data: dict):
    phone = data.get("sender", "")
    message = data.get("message", "")
    return {"phone": phone, "message": message}