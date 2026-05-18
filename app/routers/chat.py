from fastapi import APIRouter, Request, BackgroundTasks, UploadFile, File, Form
from pydantic import BaseModel
from app.services.ai_service import process_command, generate_briefing, extract_tasks, generate_wa_reply
from app.services.agent_runtime import run_sales_agent
from app.services.gmail_service import get_recent_emails, send_email
from app.services.whatsapp_service import send_whatsapp, receive_whatsapp_message, broadcast_whatsapp
from app.services.database_service import (
    get_connection,
    init_db, get_wa_messages, mark_replied,
    save_user_profile, get_user_profile, get_all_active_users,
    save_fcm_token_db, get_fcm_token_db, update_user_fcm_token,
    get_user_plan, init_user_plan, increment_daily_commands, upgrade_user_plan,
    extend_trial
)
from app.services.calendar_service import get_upcoming_events
from app.services.memory_service import (
    init_memory_db, get_customer_memory, update_customer_memory,
    get_all_customers, build_customer_context,
    save_brain_entry, get_brain_entry, get_all_brain_entries,
    get_pending_follow_ups, mark_brain_follow_up_sent, search_brain
)
import httpx
import json
import os
import base64
import tempfile
import datetime
from typing import Optional

init_db()
init_memory_db()
router = APIRouter(prefix="/chat", tags=["chat"])

WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "http://localhost:3000")


# ── Models ─────────────────────────────────────────────────
class CommandRequest(BaseModel):
    message: str
    user_id: str = "default"

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    user_id: str = "default"

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
    user_id: str = "default"

class UpdateMemoryRequest(BaseModel):
    phone: str
    message: str
    reply: str

class SaveFcmTokenRequest(BaseModel):
    token: str
    user_id: str = "default"

class BroadcastRequest(BaseModel):
    message: str
    target: str = "all"
    user_id: str = "default"

class SaveUserProfileRequest(BaseModel):
    user_id: str
    name: str
    email: str
    phone: str
    city: str = "Jakarta"
    briefing_hour: int = 6
    gmail_access_token: str = ""
    gmail_id_token: str = "" 

class SaveBrainRequest(BaseModel):
    user_id: str = "default"
    entity_name: str
    notes: str
    entity_type: str = "contact"
    follow_up_date: str = ""

class MarkPaidRequest(BaseModel):
    invoice_number: str
    user_id: str = "default"

class UpgradePlanRequest(BaseModel):
    user_id: str
    plan: str


# ── FCM Helper ─────────────────────────────────────────────
def get_fcm_token(user_id: str = "default") -> str:
    return get_fcm_token_db(user_id)


async def send_fcm_notification(title: str, body: str, data: dict = {},
                                 user_id: str = "default"):
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

        token = get_fcm_token(user_id)
        if not token:
            print(f"[FCM] Token tidak ada untuk user {user_id}")
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
        print(f"[FCM] Notif terkirim ke {user_id}: {response}")
    except Exception as e:
        print(f"[FCM ERROR] {e}")


async def send_fcm_to_all_users(title: str, body: str, data: dict = {}):
    users = get_all_active_users()
    for user in users:
        if user.get("fcm_token"):
            await send_fcm_notification(title, body, data, user["user_id"])


# ── Plan Helper ────────────────────────────────────────────
def _plan_label(plan: str) -> str:
    labels = {
        'trial': '✨ Trial',
        'apex': '⚡ Apex',
        'zenith': '👑 Zenith',
        'free': '🆓 Free',
    }
    return labels.get(plan, '🆓 Free')


def _limit_response(plan_info: dict) -> dict:
    plan = plan_info.get("plan", "free")
    daily_commands = plan_info.get("daily_commands", 0)
    daily_limit = plan_info.get("daily_limit", 10)

    if plan == 'free':
        reply = (
            f"⚠️ *Batas harian tercapai!*\n\n"
            f"Kamu sudah menggunakan {daily_commands}/{daily_limit} perintah hari ini.\n\n"
            f"🔄 Limit reset otomatis tengah malam.\n\n"
            f"Atau upgrade ke *⚡ Apex* untuk unlimited perintah!\n"
            f"Hanya *Rp 120.000/bulan* — coba gratis 3 hari!"
        )
    else:
        reply = f"⚠️ Batas penggunaan tercapai. Hubungi support."

    return {
        "status": "limit_reached",
        "message": reply,
        "response": reply,
        "emails": [],
        "parsed": {
            "intent": "limit_reached",
            "summary": reply,
            "action": "limit",
            "needs_confirmation": False,
            "draft": "",
            "reply": reply,
            "reply_to": "",
            "subject": "",
            "plan_info": plan_info
        }
    }


# ── Broadcast Helper ───────────────────────────────────────
async def _run_broadcast(phones: list, message: str, user_id: str = "default"):
    try:
        print(f"[BROADCAST] Mulai kirim ke {len(phones)} nomor...")
        result = broadcast_whatsapp(phones, message, delay=2.0)
        print(f"[BROADCAST] Selesai: {result['success']} berhasil, {result['failed']} gagal")
        await send_fcm_notification(
            title="📢 Broadcast Selesai!",
            body=f"Terkirim ke {result['success']}/{result['total']} customer",
            data={"type": "broadcast"},
            user_id=user_id
        )
    except Exception as e:
        print(f"[BROADCAST ERROR] {e}")


# ── Health Check ───────────────────────────────────────────
@router.get("/health")
async def health_check():
    """✅ Cek kesehatan semua service Orion AI"""
    try:
        from app.services.ai_provider import get_health_status
        ai_health = get_health_status()
    except Exception as e:
        ai_health = {"error": str(e)}

    wa_status = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(f"{WA_GATEWAY_URL}/status")
            wa_status = res.json().get("connected", False)
    except:
        pass

    gmail_status = False
    try:
        from app.services.gmail_service import get_gmail_service
        get_gmail_service()
        gmail_status = True
    except:
        pass

    db_status = False
    try:
        conn, _db_type = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1")
        conn.close()
        db_status = True
    except:
        pass

    overall = (
        db_status and
        isinstance(ai_health, dict) and
        any(v.get("healthy", False) for v in ai_health.values()
            if isinstance(v, dict))
    )

    return {
        "status": "ok",
        "timestamp": datetime.datetime.now().isoformat(),
        "services": {
            "database": "✅ OK" if db_status else "❌ ERROR",
            "gmail": "✅ OK" if gmail_status else "⚠️ Token expired",
            "wa_gateway": "✅ Connected" if wa_status else "⚠️ Disconnected",
        },
        "ai_providers": ai_health,
        "overall_healthy": overall,
    }


# ── Endpoints ──────────────────────────────────────────────

@router.post("/save-fcm-token")
async def save_fcm_token(request: SaveFcmTokenRequest):
    try:
        save_fcm_token_db(request.token, request.user_id)
        update_user_fcm_token(request.user_id, request.token)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/save-user-profile")
async def save_user_profile_endpoint(request: SaveUserProfileRequest):
    try:
        save_user_profile(
            user_id=request.user_id,
            name=request.name,
            email=request.email,
            phone=request.phone,
            city=request.city,
            briefing_hour=request.briefing_hour
        )
        if request.gmail_access_token:
            save_user_gmail_token(
                user_id=request.user_id,
                access_token=request.gmail_access_token,
                id_token=request.gmail_id_token
            )
        init_user_plan(request.user_id)
        return {"status": "success", "message": f"Profil {request.name} tersimpan"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/user-profile/{user_id}")
async def get_user_profile_endpoint(user_id: str):
    try:
        profile = get_user_profile(user_id)
        plan_info = get_user_plan(user_id)
        return {"status": "success", "profile": profile, "plan": plan_info}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Plan Endpoints ─────────────────────────────────────────

@router.get("/plan/{user_id}")
async def get_plan(user_id: str):
    try:
        init_user_plan(user_id)
        plan_info = get_user_plan(user_id)
        plan = plan_info.get("plan", "free")

        features = {
            'trial': [
                "✅ Semua fitur Apex & Zenith",
                "✅ Unlimited perintah",
                "✅ Unlimited email & WA",
                "✅ Broadcast unlimited",
                "✅ Meeting transcriber",
                f"⏰ Berakhir dalam {plan_info.get('trial_days_left', 0)} hari",
            ],
            'apex': [
                "✅ Unlimited perintah",
                "✅ Email auto-reply unlimited",
                "✅ Invoice & payment unlimited",
                "✅ WA auto-reply unlimited",
                "✅ Broadcast 500 kontak",
                "✅ Quotation PDF unlimited",
                "✅ Meeting transcriber 5x/bulan",
                "✅ Personal Brain & follow up",
            ],
            'zenith': [
                "👑 Semua fitur Apex",
                "👑 Unlimited segalanya",
                "👑 Broadcast unlimited kontak",
                "👑 Meeting transcriber unlimited",
                "👑 Sales AI closing premium",
                "👑 Multi-user (2 akun)",
                "👑 White label",
                "👑 Priority support 24/7",
            ],
            'free': [
                f"⚡ {plan_info.get('daily_commands', 0)}/{plan_info.get('daily_limit', 10)} perintah hari ini",
                "❌ Tidak bisa broadcast",
                "❌ Invoice terbatas",
                "❌ Meeting transcriber tidak tersedia",
                "🔄 Reset tiap tengah malam",
            ],
        }

        return {
            "status": "success",
            "plan": plan_info,
            "label": _plan_label(plan),
            "features": features.get(plan, features['free']),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/plan/upgrade")
async def upgrade_plan(request: UpgradePlanRequest):
    try:
        if request.plan not in ['apex', 'zenith', 'free']:
            return {"status": "error", "message": "Plan tidak valid"}
        upgrade_user_plan(request.user_id, request.plan)
        plan_info = get_user_plan(request.user_id)
        return {
            "status": "success",
            "message": f"🎉 Plan berhasil diupgrade ke {_plan_label(request.plan)}!",
            "plan": plan_info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Main Chat Endpoint ─────────────────────────────────────

@router.post("/")
async def chat(request: CommandRequest):
    try:
        if request.user_id and request.user_id != "default":
            init_user_plan(request.user_id)
            plan_info = get_user_plan(request.user_id)
            if not plan_info.get("can_use", True):
                return _limit_response(plan_info)
            increment_daily_commands(request.user_id)

        result = await process_command(request.message, request.user_id)

        if request.user_id and request.user_id != "default":
            try:
                plan_info = get_user_plan(request.user_id)
                if result.get("parsed"):
                    result["parsed"]["plan_info"] = {
                        "plan": plan_info.get("plan"),
                        "is_trial": plan_info.get("is_trial"),
                        "trial_days_left": plan_info.get("trial_days_left"),
                        "daily_commands": plan_info.get("daily_commands"),
                        "daily_limit": plan_info.get("daily_limit"),
                    }
            except:
                pass

        return result

    except Exception as e:
        print(f"[CHAT ERROR] {e}")
        return {
            "status": "error",
            "message": str(e),
            "response": "Terjadi kesalahan. Coba lagi ya!",
            "emails": [],
            "parsed": {
                "intent": "error",
                "summary": "Error",
                "action": "error",
                "needs_confirmation": False,
                "draft": "",
                "reply": "Terjadi kesalahan. Coba lagi ya!",
                "reply_to": "",
                "subject": ""
            }
        }


@router.get("/emails")
async def read_emails():
    try:
        emails = get_recent_emails()
        return {"status": "success", "emails": emails}
    except Exception as e:
        print(f"[EMAILS ERROR] {e}")
        return {"status": "error", "emails": [], "message": str(e)}


@router.post("/send-email")
async def send_email_endpoint(request: SendEmailRequest):
    try:
        result = send_email(request.to, request.subject, request.body)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/send-whatsapp")
async def send_whatsapp_endpoint(request: SendWhatsAppRequest):
    try:
        result = send_whatsapp(request.phone, request.message)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/whatsapp-messages")
async def get_whatsapp_messages(user_id: str = "default"):
    try:
        messages = get_wa_messages(limit=10, user_id=user_id)
        return {"status": "success", "messages": messages}
    except Exception as e:
        return {"status": "error", "messages": [], "message": str(e)}


@router.get("/briefing")
async def get_briefing(user_id: str = "default"):
    try:
        result = await generate_briefing(user_id=user_id)
        try:
            if result and result.get("urgent") and len(result["urgent"]) > 0:
                await send_fcm_notification(
                    title="📧 Email Urgent!",
                    body=f"Ada {len(result['urgent'])} email urgent",
                    data={"type": "email"},
                    user_id=user_id
                )
        except Exception as fcm_err:
            print(f"[FCM BRIEFING ERROR] {fcm_err}")
        return {"status": "success", "briefing": result}
    except Exception as e:
        print(f"[BRIEFING ERROR] {e}")
        # Graceful fallback — tidak crash app
        return {
            "status": "success",
            "briefing": {
                "urgent": [],
                "bisa_nanti": [],
                "arsip": [],
                "summary": "Email tidak dapat dimuat saat ini. Coba lagi nanti."
            }
        }


@router.get("/tasks")
async def get_tasks(user_id: str = "default"):
    try:
        result = await extract_tasks(user_id=user_id)
        try:
            if result and result.get("tasks"):
                high_priority = [t for t in result["tasks"]
                                 if t.get("priority") == "high"]
                if high_priority:
                    await send_fcm_notification(
                        title="✅ Task Urgent!",
                        body=f"Ada {len(high_priority)} task prioritas tinggi",
                        data={"type": "task"},
                        user_id=user_id
                    )
        except Exception as fcm_err:
            print(f"[FCM TASKS ERROR] {fcm_err}")
        return {"status": "success", "tasks": result}
    except Exception as e:
        print(f"[TASKS ERROR] {e}")
        # Graceful fallback — tidak crash app
        return {
            "status": "success",
            "tasks": {
                "tasks": [],
                "summary": "Tasks tidak dapat dimuat saat ini. Coba lagi nanti."
            }
        }


@router.get("/calendar-events")
async def get_calendar_events():
    try:
        events = get_upcoming_events(max_results=10)
        return {"status": "success", "events": events}
    except Exception as e:
        print(f"[CALENDAR ERROR] {e}")
        return {"status": "success", "events": [], "message": str(e)}


@router.get("/customer-memory/{phone}")
async def get_memory(phone: str):
    try:
        context = build_customer_context(phone)
        memory = get_customer_memory(phone)
        return {"status": "success", "context": context, "memory": memory}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
    try:
        result = await generate_wa_reply(request.message, request.business_context)
        return {"status": "success", "reply": result}
    except Exception as e:
        return {"status": "success", "reply": "Terima kasih atas pesan Anda. Kami akan segera membalas."}


@router.get("/wa-qr")
async def get_wa_qr(user_id: str = "default"):
    import asyncio
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Trigger connect dulu
            try:
                await client.post(f"{WA_GATEWAY_URL}/connect", json={"user_id": user_id})
            except:
                pass
            # Tunggu QR generate
            await asyncio.sleep(8)
            # Ambil QR
            res = await client.get(f"{WA_GATEWAY_URL}/qr?user_id={user_id}")
            data = res.json()
            return {"status": "success", "qr_url": data.get("qr_url", "")}
    except Exception as e:
        return {"status": "error", "qr_url": "", "error": str(e)}


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
        profile_data = request.dict()
        user_id = profile_data.pop("user_id", "default")
        os.makedirs("profiles", exist_ok=True)
        with open(f"profiles/{user_id}_business.json", "w") as f:
            json.dump(profile_data, f, indent=2, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/broadcast")
async def broadcast(request: BroadcastRequest, background_tasks: BackgroundTasks):
    try:
        if request.user_id and request.user_id != "default":
            plan_info = get_user_plan(request.user_id)
            if plan_info.get("plan") == "free":
                return {
                    "status": "error",
                    "message": "⚠️ Broadcast hanya tersedia untuk plan Apex dan Zenith."
                }

        customers = get_all_customers()
        if not customers:
            return {"status": "error", "message": "Tidak ada customer ditemukan"}
        phones = [c["phone"] for c in customers if c.get("phone")]
        if not phones:
            return {"status": "error", "message": "Tidak ada nomor customer"}
        background_tasks.add_task(_run_broadcast, phones, request.message, request.user_id)
        return {
            "status": "success",
            "message": f"Broadcast dimulai ke {len(phones)} customer",
            "total": len(phones)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Invoice Endpoints ──────────────────────────────────────

@router.get("/invoices/{user_id}")
async def get_invoices(user_id: str):
    try:
        if not user_id or user_id == "default":
            return {"status": "error", "invoices": [], "message": "User tidak valid"}
        from app.services.payment_service import get_all_invoices, init_payment_db
        init_payment_db()
        invoices = get_all_invoices(user_id)
        return {"status": "success", "invoices": invoices}
    except Exception as e:
        return {"status": "error", "invoices": [], "message": str(e)}


@router.post("/invoices/mark-paid")
async def mark_invoice_paid_endpoint(request: MarkPaidRequest):
    try:
        if not request.user_id or request.user_id == "default":
            return {"status": "error", "message": "User tidak valid"}
        from app.services.payment_service import mark_invoice_paid
        success = mark_invoice_paid(request.invoice_number, request.user_id)
        if success:
            return {"status": "success",
                    "message": f"Invoice {request.invoice_number} ditandai lunas"}
        else:
            return {"status": "error",
                    "message": f"Invoice {request.invoice_number} tidak ditemukan"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/invoices/summary/{user_id}")
async def get_invoice_summary(user_id: str):
    try:
        if not user_id or user_id == "default":
            return {"status": "error", "summary": {}}
        from app.services.payment_service import get_all_invoices, init_payment_db
        init_payment_db()
        invoices = get_all_invoices(user_id)
        unpaid = [i for i in invoices if i['status'] == 'unpaid']
        paid = [i for i in invoices if i['status'] == 'paid']
        return {
            "status": "success",
            "summary": {
                "total_invoices": len(invoices),
                "unpaid_count": len(unpaid),
                "paid_count": len(paid),
                "total_unpaid": sum(i['amount'] for i in unpaid),
                "total_paid": sum(i['amount'] for i in paid),
            }
        }
    except Exception as e:
        return {"status": "error", "summary": {}, "message": str(e)}


# ── Personal Brain Endpoints ───────────────────────────────

@router.post("/brain/save")
async def brain_save(request: SaveBrainRequest):
    try:
        save_brain_entry(
            user_id=request.user_id,
            entity_name=request.entity_name,
            notes=request.notes,
            entity_type=request.entity_type,
            follow_up_date=request.follow_up_date
        )
        return {"status": "success", "message": f"Tersimpan: {request.entity_name}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/brain/list/{user_id}")
async def brain_list(user_id: str):
    try:
        entries = get_all_brain_entries(user_id)
        return {"status": "success", "entries": entries}
    except Exception as e:
        return {"status": "error", "entries": [], "message": str(e)}


@router.get("/brain/search/{user_id}")
async def brain_search(user_id: str, q: str = ""):
    try:
        results = search_brain(user_id, q)
        return {"status": "success", "results": results}
    except Exception as e:
        return {"status": "error", "results": [], "message": str(e)}


@router.get("/brain/follow-ups/{user_id}")
async def brain_follow_ups(user_id: str):
    try:
        follow_ups = get_pending_follow_ups(user_id)
        return {"status": "success", "follow_ups": follow_ups}
    except Exception as e:
        return {"status": "error", "follow_ups": [], "message": str(e)}


# ── Meeting Transcriber ────────────────────────────────────

@router.post("/transcribe-meeting")
async def transcribe_meeting(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    meeting_title: str = Form(default="Meeting"),
    participant_emails: str = Form(default=""),
    language: str = Form(default="id"),
    user_id: str = Form(default="default"),
):
    try:
        if user_id and user_id != "default":
            plan_info = get_user_plan(user_id)
            if plan_info.get("plan") == "free":
                return {
                    "status": "error",
                    "message": "⚠️ Meeting Transcriber hanya tersedia untuk Apex dan Zenith."
                }

        filename = audio.filename or "audio.mp3"
        suffix = os.path.splitext(filename)[1] or ".mp3"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp") as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name

        emails_list = []
        if participant_emails:
            emails_list = [e.strip() for e in participant_emails.split(",")
                          if e.strip() and "@" in e.strip()]

        background_tasks.add_task(
            _process_meeting_background,
            tmp_path, meeting_title, emails_list, language, user_id
        )

        return {
            "status": "success",
            "message": f"Meeting '{meeting_title}' sedang diproses...",
            "file_size": len(content),
            "emails_to_notify": len(emails_list)
        }

    except Exception as e:
        print(f"[MEETING UPLOAD ERROR] {e}")
        return {"status": "error", "message": str(e)}


async def _process_meeting_background(
    audio_path: str,
    meeting_title: str,
    participant_emails: list,
    language: str,
    user_id: str
):
    try:
        from app.services.transcriber_service import process_meeting
        result = await process_meeting(
            audio_path=audio_path,
            meeting_title=meeting_title,
            participant_emails=participant_emails,
            language=language
        )
        if result["status"] == "success":
            await send_fcm_notification(
                title="🎙️ Meeting Selesai Diproses!",
                body=f"Notulen '{meeting_title}' siap.",
                data={"type": "meeting", "summary": result["summary"][:200]},
                user_id=user_id
            )
        else:
            await send_fcm_notification(
                title="❌ Gagal Proses Meeting",
                body=result.get("message", "Terjadi kesalahan"),
                data={"type": "meeting_error"},
                user_id=user_id
            )
        try:
            os.remove(audio_path)
        except:
            pass
    except Exception as e:
        print(f"[MEETING BG ERROR] {e}")
        await send_fcm_notification(
            title="❌ Gagal Proses Meeting",
            body=str(e),
            data={"type": "meeting_error"},
            user_id=user_id
        )


# ── WhatsApp Webhook ───────────────────────────────────────

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    try:
        data = await request.json()
        incoming = receive_whatsapp_message(data)

        if not incoming.get("message") or not incoming.get("phone"):
            return {"status": "ok"}

        phone = incoming["phone"]
        message = incoming["message"]

        user_id = data.get("user_id") or "AZVICKYFADZRY02GMAILCOM"
        print(f"[WEBHOOK] {phone} -> {user_id}: {message[:30]}")
        customer_context = build_customer_context(phone)

        try:
            # APEX Agent Runtime — full context + CRM state machine
            agent_result = await run_sales_agent(
                user_id=user_id,
                phone=phone,
                message=message,
            )
            ai_result = agent_result.get('reply', 'Terima kasih atas pesan Anda!')
        except Exception as ai_err:
            print(f"[WA REPLY AI ERROR] {ai_err}")
            ai_result = "Terima kasih atas pesan Anda. Kami akan segera membalas."

        reply_text = ""
        if isinstance(ai_result, dict):
            reply_text = (
                ai_result.get("reply") or
                ai_result.get("draft") or
                ai_result.get("summary") or
                "Terima kasih atas pesan Anda."
            )
        elif isinstance(ai_result, str):
            reply_text = ai_result
        else:
            reply_text = "Terima kasih atas pesan Anda. Kami akan segera membalas."

        try:
            from app.services.whatsapp_service import send_whatsapp_baileys
            print(f"[WA SEND] Sending reply to {phone}: {reply_text[:50]}")
            result = send_whatsapp_baileys(phone, reply_text, user_id=user_id)
            print(f"[WA SEND] Result: {result}")
            mark_replied(phone)
        except Exception as send_err:
            print(f"[WA SEND ERROR] {send_err}")

        try:
            update_customer_memory(phone, message, reply_text, user_id)
        except Exception as mem_err:
            print(f"[MEMORY ERROR] {mem_err}")

        try:
            sender = phone.replace("@lid", "").replace("@s.whatsapp.net", "")
            await send_fcm_notification(
                title=f"💬 WA dari {sender}",
                body=message[:100],
                data={"type": "wa", "phone": phone},
                user_id=user_id
            )
        except Exception as fcm_err:
            print(f"[FCM WA ERROR] {fcm_err}")

        return {"status": "ok"}

    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
        return {"status": "ok"}  # Selalu return ok agar WA tidak retry

@router.post("/admin/extend-trial")
async def extend_trial_endpoint(request: Request):
    try:
        body = await request.json()
        user_id = body.get("user_id")
        days = body.get("days", 30)
        secret = body.get("secret", "")
        if secret != "orion-admin-2026":
            return {"status": "error", "message": "Unauthorized"}
        result = extend_trial(user_id, days)
        return {"status": "success" if result else "error", "user_id": user_id, "days": days}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/admin/debug-db")
async def debug_db():
    import os, sqlite3
    try:
        conn, _db_type = get_connection()
        c = conn.cursor()
        c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        tables = [row[0] for row in c.fetchall()]
        conn.close()
        return {"tables": tables, "db": "postgresql"}
    except Exception as e:
        return {"error": str(e), "db_path": DB_PATH}


@router.post("/admin/init-db")
async def init_db_endpoint(request: Request):
    try:
        body = await request.json()
        secret = body.get("secret", "")
        if secret != "orion-admin-2026":
            return {"status": "error", "message": "Unauthorized"}
        init_db()
        from app.services.zenith_service import init_zenith_db
        init_zenith_db()
        return {"status": "success", "message": "Database initialized!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── Payment iPaymu ───────────────────────────────────────
@router.post("/create-payment")
async def create_payment_endpoint(request: Request):
    try:
        data = await request.json()
        from app.services.payment_service import create_payment
        result = await create_payment(
            user_id=data.get("user_id"),
            plan=data.get("plan"),
            user_email=data.get("email"),
            user_name=data.get("name"),
        )
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/payment-webhook")
async def payment_webhook(request: Request):
    try:
        data = await request.json()
        print(f"[PAYMENT WEBHOOK] {data}")
        reference_id = data.get("reference_id") or data.get("referenceId", "")
        status = data.get("status", "")
        if status in ["SUCCESS", "PAID", "settlement"] and reference_id:
            parts = reference_id.split("-")
            if len(parts) >= 3:
                user_id = parts[1]
                plan = parts[2]
                from app.services.database_service import get_connection
                conn, _ = get_connection()
                try:
                    c = conn.cursor()
                    c.execute("UPDATE users SET plan = %s, updated_at = NOW() WHERE user_id = %s", (plan, user_id))
                    conn.commit()
                finally:
                    conn.close()
                print(f"[PAYMENT] ✅ User {user_id} upgraded to {plan}")
        return {"status": "ok"}
    except Exception as e:
        print(f"[PAYMENT WEBHOOK ERROR] {e}")
        return {"status": "ok"}

# ── Trigger Briefing Manual ───────────────────────────────────────
@router.post("/trigger-briefing")
async def trigger_briefing(request: Request):
    try:
        data = await request.json()
        if data.get("secret") != "orion-admin-2026":
            return {"status": "error", "message": "Unauthorized"}
        from app.services.scheduler_service import daily_intelligence_briefing
        await daily_intelligence_briefing()
        return {"status": "success", "message": "Briefing triggered!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── Update Profile ───────────────────────────────────────
@router.post("/update-profile")
async def update_profile(request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        phone = data.get("phone", "")
        business_name = data.get("business_name", "")
        business_context = data.get("business_context", "")
        
        from app.services.database_service import get_connection
        conn, _ = get_connection()
        try:
            c = conn.cursor()
            c.execute("""
                UPDATE users SET
                    phone = %s,
                    business_name = %s,
                    business_context = %s,
                    updated_at = NOW()
                WHERE user_id = %s
            """, (phone, business_name, business_context, user_id))
            conn.commit()
        finally:
            conn.close()
        
        print(f"[PROFILE] Updated for {user_id}")
        return {"status": "success", "message": "Profile updated!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── SOP Bisnis ───────────────────────────────────────
@router.post("/save-sop")
async def save_sop(request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        sop_type = data.get("sop_type", "general")
        content = data.get("content", "")
        
        from app.services.database_service import get_connection
        conn, _ = get_connection()
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO workspace_sop (user_id, sop_type, content, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (user_id, sop_type)
                DO UPDATE SET content = %s, updated_at = NOW()
            """, (user_id, sop_type, content, content))
            conn.commit()
        finally:
            conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/get-sop/{user_id}")
async def get_sop(user_id: str):
    try:
        from app.services.database_service import get_connection
        conn, _ = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT sop_type, content FROM workspace_sop WHERE user_id = %s", (user_id,))
            rows = c.fetchall()
        finally:
            conn.close()
        return {"status": "success", "sop": [{"type": r[0], "content": r[1]} for r in rows]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── Real-time Notifications SSE ───────────────────────────────────────
import asyncio
from fastapi.responses import StreamingResponse

notification_queues = {}

@router.get("/notifications/stream/{user_id}")
async def notification_stream(user_id: str):
    async def event_generator():
        queue = asyncio.Queue()
        notification_queues[user_id] = queue
        try:
            while True:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except Exception:
            pass
        finally:
            notification_queues.pop(user_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/notifications/send")
async def send_notification(request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        if user_id in notification_queues:
            await notification_queues[user_id].put(data)
        return {"status": "sent"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── Calendar ───────────────────────────────────────
@router.get("/calendar/{user_id}")
async def get_calendar(user_id: str):
    try:
        import asyncio
        from app.services.calendar_service import get_upcoming_events
        result = await asyncio.to_thread(get_upcoming_events, user_id)
        if result.get("reauth_required"):
            return {"status": "reauth_required", "message": "Silakan login ulang untuk mengaktifkan Google Calendar"}
        return {"status": "success", "events": result.get("events", [])}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/calendar/add")
async def add_calendar(request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        if not user_id:
            return {"status": "error", "message": "user_id wajib diisi"}
        from app.services.calendar_service import add_calendar_event
        from datetime import datetime, timedelta
        start_time = data.get("start_time", datetime.now().isoformat())
        duration_hours = data.get("duration_hours", 1)
        try:
            start_dt = datetime.fromisoformat(start_time)
        except:
            start_dt = datetime.now() + timedelta(days=1)
        end_dt = start_dt + timedelta(hours=duration_hours)
        result = add_calendar_event(
            user_id=user_id,
            title=data.get("title", ""),
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            description=data.get("description", "")
        )
        if result.get("reauth_required"):
            return {"status": "reauth_required", "message": "Silakan login ulang untuk mengaktifkan Google Calendar"}
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}
