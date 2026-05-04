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
import sqlite3
import base64

init_db()
init_memory_db()
router = APIRouter(prefix="/chat", tags=["chat"])

WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "http://localhost:3000")
DB_PATH = os.getenv("DB_PATH", "orion.db")

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

class SaveFcmTokenRequest(BaseModel):
    token: str

# ── FCM Helper ─────────────────────────────────────────────
def save_fcm_token_db(token: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS fcm_tokens 
                     (id INTEGER PRIMARY KEY, token TEXT UNIQUE, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute("INSERT OR REPLACE INTO fcm_tokens (id, token) VALUES (1, ?)", (token,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[FCM DB ERROR] {e}")

def get_fcm_token() -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT token FROM fcm_tokens WHERE id = 1")
        row = c.fetchone()
        conn.close()
        return row[0] if row else ""
    except:
        return ""

async def send_fcm_notification(title: str, body: str, data: dict = {}):
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        if not firebase_admin._apps:
            sa_base64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_BASE64", "")
            if not sa_base64:
                print("[FCM] FIREBASE_SERVICE_ACCOUNT_BASE64 tidak ada")
                return
            sa_json = json.loads(base64.b64decode(sa_base64).decode('utf-8'))
            cred = credentials.Certificate(sa_json)
            firebase_admin.initialize_app(cred)

        token = get_fcm_token()
        if not token:
            print("[FCM] Token tidak ada")
            return

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in data.items()},
            token=token,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    priority='high',
                ),
            ),
        )
        response = messaging.send(message)
        print(f"[FCM] Notif terkirim: {response}")
    except Exception as e:
        print(f"[FCM ERROR] {e}")

# ── Endpoints ──────────────────────────────────────────────
@router.post("/save-fcm-token")
async def save_fcm_token(request: SaveFcmTokenRequest):
    try:
        save_fcm_token_db(request.token)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
    try:
        if result and result.get("urgent") and len(result["urgent"]) > 0:
            urgent_count = len(result["urgent"])
            await send_fcm_notification(
                title="📧 Email Urgent!",
                body=f"Ada {urgent_count} email urgent yang perlu dibalas",
                data={"type": "email"}
            )
    except Exception as e:
        print(f"[FCM BRIEFING ERROR] {e}")
    return {"status": "success", "briefing": result}

@router.get("/tasks")
async def get_tasks():
    result = await extract_tasks()
    try:
        if result and result.get("tasks") and len(result["tasks"]) > 0:
            high_priority = [t for t in result["tasks"] if t.get("priority") == "high"]
            if high_priority:
                await send_fcm_notification(
                    title="✅ Task Urgent!",
                    body=f"Ada {len(high_priority)} task prioritas tinggi",
                    data={"type": "task"}
                )
    except Exception as e:
        print(f"[FCM TASKS ERROR] {e}")
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

    phone = incoming["phone"]
    message = incoming["message"]

    customer_context = build_customer_context(phone)
    ai_result = await generate_wa_reply(message, customer_context)

    reply_text = ""
    try:
        if isinstance(ai_result, dict):
            reply_text = (
                ai_result.get("reply")
                or ai_result.get("draft")
                or ai_result.get("summary")
                or "Terima kasih atas pesan Anda."
            )
        elif isinstance(ai_result, str):
            reply_text = ai_result
        else:
            reply_text = "Terima kasih atas pesan Anda. Kami akan segera membalas."
    except Exception:
        reply_text = "Terima kasih atas pesan Anda. Kami akan segera membalas."

    send_whatsapp(phone, reply_text)
    mark_replied(phone)

    try:
        update_customer_memory(phone, message, reply_text)
    except Exception as e:
        print(f"[MEMORY ERROR] {phone}: {e}")

    try:
        sender = phone.replace("@lid", "").replace("@s.whatsapp.net", "")
        await send_fcm_notification(
            title=f"💬 WA dari {sender}",
            body=message[:100],
            data={"type": "wa", "phone": phone}
        )
    except Exception as e:
        print(f"[FCM WA ERROR] {e}")

    return {"status": "ok"}