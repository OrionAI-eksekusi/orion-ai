from fastapi import APIRouter, Request
from pydantic import BaseModel
from app.services.ai_service import process_command, generate_briefing, extract_tasks
from app.services.gmail_service import get_recent_emails, send_email
from app.services.whatsapp_service import send_whatsapp, receive_whatsapp_message
from app.services.database_service import init_db, get_wa_messages, mark_replied

init_db()

router = APIRouter(prefix="/chat", tags=["chat"])

class CommandRequest(BaseModel):
    message: str

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str

class SendWhatsAppRequest(BaseModel):
    phone: str
    message: str

@router.post("/")
async def chat(request: CommandRequest):
    result = await process_command(request.message)
    return result

@router.get("/emails")
async def read_emails():
    emails = get_recent_emails()
    return {"status": "success", "emails": emails}

@router.post("/send-email")
async def send_email_endpoint(request: SendEmailRequest):
    result = send_email(request.to, request.subject, request.body)
    return result

@router.post("/send-whatsapp")
async def send_whatsapp_endpoint(request: SendWhatsAppRequest):
    result = send_whatsapp(request.phone, request.message)
    return result

@router.get("/whatsapp-messages")
async def get_whatsapp_messages():
    messages = get_wa_messages(limit=10)
    return {"status": "success", "messages": messages}

@router.get("/briefing")
async def get_briefing():
    result = await generate_briefing()
    return {"status": "success", "briefing": result}

@router.get("/tasks")
async def get_tasks():
    result = await extract_tasks()
    return {"status": "success", "tasks": result}

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    incoming = receive_whatsapp_message(data)
    if not incoming["message"] or not incoming["phone"]:
        return {"status": "ok"}
    ai_result = await process_command(incoming["message"])
    reply_text = ""
    try:
        parsed = ai_result.get("parsed", {})
        if parsed.get("draft"):
            reply_text = parsed["draft"]
        else:
            reply_text = parsed.get("summary", "Terima kasih atas pesan Anda.")
    except:
        reply_text = "Terima kasih atas pesan Anda. Kami akan segera membalas."
    send_whatsapp(incoming["phone"], reply_text)
    mark_replied(incoming["phone"])
    return {"status": "ok"}