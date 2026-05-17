"""
APEX Queue Service — ARQ (Python Redis Queue)
Event-driven async job processing
"""
import arq
from arq.connections import RedisSettings
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://default:dGSnGRIepyjJTRfZZvpmzxVTqzWmHbJl@redis.railway.internal:6379")

def get_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(REDIS_URL)

async def get_arq_pool():
    return await arq.create_pool(get_redis_settings())

# Job definitions
async def process_wa_message(ctx, payload: dict):
    """Process incoming WhatsApp message through AI pipeline"""
    from app.services.context_engine import aggregate_context
    from app.services.ai_service import generate_wa_reply
    
    user_id = payload.get("user_id")
    phone = payload.get("phone")
    message = payload.get("message")
    
    print(f"[QUEUE] Processing WA message from {phone}")
    
    # Aggregate context in parallel
    context = await aggregate_context(user_id, phone)
    
    # Generate AI reply
    reply = await generate_wa_reply(message, str(context))
    
    return {"status": "processed", "reply": reply}

async def send_smart_briefing(ctx, user_id: str):
    """Send daily smart briefing to user"""
    from app.services.ai_service import generate_briefing
    print(f"[QUEUE] Sending briefing to {user_id}")
    return {"status": "sent"}

async def process_invoice_ocr(ctx, payload: dict):
    """Process invoice OCR and price guard analysis"""
    print(f"[QUEUE] Processing invoice OCR")
    return {"status": "processed"}

# Worker settings
class WorkerSettings:
    functions = [
        process_wa_message,
        send_smart_briefing,
        process_invoice_ocr,
    ]
    redis_settings = get_redis_settings()
    max_jobs = 10
    job_timeout = 300