from fastapi import APIRouter, Request
from pydantic import BaseModel
from app.services.ai_service import process_command
from app.services.gmail_service import get_recent_emails, send_email
from app.services.whatsapp_service import send_whatsapp, receive_whatsapp_message

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

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    incoming = receive_whatsapp_message(data)
    ai_result = await process_command(incoming["message"])
    send_whatsapp(incoming["phone"], ai_result["response"])
    return {"status": "ok"}