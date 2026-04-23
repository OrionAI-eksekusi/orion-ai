import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

async def process_command(message: str):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    email_keywords = ['email', 'balas', 'inbox', 'pesan masuk', 'surat']
    is_email_command = any(word in message.lower() for word in email_keywords)
    
    email_context = ""
    emails = []
    
    if is_email_command:
        try:
            from app.services.gmail_service import get_recent_emails
            emails = get_recent_emails(max_results=3)
            email_context = f"Email terbaru di inbox: {json.dumps(emails, indent=2)}"
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

Selalu jawab dalam format JSON:
{{
    "intent": "nama_aksi",
    "summary": "ringkasan aksi dalam bahasa Indonesia",
    "action": "detail teknis aksi",
    "needs_confirmation": true,
    "draft": "draft pesan/email yang siap dikirim",
    "reply_to": "email/nomor tujuan jika ada",
    "subject": "subject jika email"
}}

Untuk pesan WhatsApp masuk, buat balasan yang sopan dan profesional dalam Bahasa Indonesia."""
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