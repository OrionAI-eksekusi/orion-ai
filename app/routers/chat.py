from fastapi import APIRouter, Request
from pydantic import BaseModel
from app.services.ai_service import process_command, generate_briefing, extract_tasks, generate_wa_reply
from app.services.gmail_service import get_recent_emails, send_email
from app.services.whatsapp_service import send_whatsapp, receive_whatsapp_message
from app.services.database_service import init_db, get_wa_messages, mark_replied
from app.services.calendar_service import get_upcoming_events
from app.services.memory_service import init_memory_db, get_customer_memory, update_customer_memory, get_all_customers, build_customer_context
import httpx
import json
import os

init_db()
init_memory_db()
router = APIRouter(prefix="/chat", tags=["chat"])

WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "http://localhost:3000")

class CommandRequest(BaseModel):
    message: str

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str

class SendWhatsAppRequest(BaseModel):
    phone: str
    message: str

class WAReplyRequest(BaseModel):
    message: str
    business_context: str
    phone: str = ""

class SaveProfileRequest(BaseModel):
    name: str
    tagline: str
    field: str
    description: str
    products: list
    how_to_order: str
    contact: dict
    working_hours: str
    location: str

class UpdateMemoryRequest(BaseModel):
    phone: str
    message: str
    reply: str

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

@router.get("/calendar-events")
async def get_calendar_events():
    try:
        events = get_upcoming_events(max_results=10)
        return {"status": "success", "events": events}
    except Exception as e:
        return {"status": "error", "events": [], "message": str(e)}

@router.get("/customer-memory/{phone}")
async def get_memory(phone: str):
    context = build_customer_context(phone)
    memory = get_customer_memory(phone)
    return {"status": "success", "context": context, "memory": memory}

@router.post("/update-memory")
async def update_memory(request: UpdateMemoryRequest):
    try:
        update_customer_memory(request.phone, request.message, request.reply)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/customers")
async def get_customers():
    try:
        customers = get_all_customers()
        return {"status": "success", "customers": customers}
    except Exception as e:
        return {"status": "error", "customers": [], "message": str(e)}

@router.post("/wa-reply")
async def wa_reply(request: WAReplyRequest):
    result = await generate_wa_reply(request.message, request.business_context)
    return {"status": "success", "reply": result}

@router.get("/wa-qr")
async def get_wa_qr():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{WA_GATEWAY_URL}/qr")
            data = res.json()
            return {"status": "success", "qr_url": data.get("qr_url", "")}
    except:
        return {"status": "error", "qr_url": ""}

@router.get("/wa-status")
async def get_wa_status():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{WA_GATEWAY_URL}/status")
            data = res.json()
            return {"connected": data.get("connected", False)}
    except:
        return {"connected": False}

@router.post("/save-profile")
async def save_profile(request: SaveProfileRequest):
    try:
        with open("business_profile.json", "w") as f:
            json.dump(request.dict(), f, indent=2, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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