import os
import json
from groq import Groq
from dotenv import load_dotenv
from app.services.gmail_service import get_recent_emails, send_email

load_dotenv()

async def process_command(message: str):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    email_keywords = ['email', 'balas', 'inbox', 'pesan masuk', 'surat']
    is_email_command = any(word in message.lower() for word in email_keywords)
    
    email_context = ""
    emails = []
    
    if is_email_command:
        try:
            emails = get_recent_emails(max_results=3)
            email_context = f"Email terbaru di inbox: {json.dumps(emails, indent=2)}"
        except Exception as e:
            email_context = "Gagal membaca email."
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": f"""Kamu adalah Orion AI, asisten eksekusi perintah. {email_context}
Selalu jawab dalam format JSON:
{{
    "intent": "nama_aksi",
    "summary": "ringkasan aksi dalam bahasa Indonesia",
    "action": "detail teknis aksi",
    "needs_confirmation": true,
    "draft": "draft balasan email jika intent balas_email",
    "reply_to": "email pengirim jika intent balas_email",
    "subject": "subject email jika intent balas_email"
}}"""
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
        return {
            "status": "success",
            "message": message,
            "response": ai_response,
            "emails": emails,
            "parsed": parsed
        }
    except:
        return {
            "status": "success",
            "message": message,
            "response": ai_response,
            "emails": emails
        }