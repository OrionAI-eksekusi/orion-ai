"""
APEX Parallel Context Engine
Aggregates all context needed by LLM before activation
Uses asyncio.gather for maximum parallelism — zero sequential blocking
"""
import asyncio
import asyncpg
import json
import os
from datetime import datetime, timedelta
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

def get_db():
    from app.services.database_service import get_connection
    conn, _ = get_connection()
    return conn

async def aggregate_context(user_id: str, phone: str = None) -> dict:
    """
    Parallel context aggregation using asyncio.gather
    All DB queries fire simultaneously — minimizes LLM activation latency
    """
    try:
        results = await asyncio.gather(
            get_chat_history(user_id, phone),
            get_long_term_memory(user_id, phone),
            get_workspace_sop(user_id),
            get_active_calendar_events(user_id),
            get_lead_state(user_id, phone),
            get_user_profile(user_id),
            return_exceptions=True
        )

        chat_history, memory, sop, calendar, lead_state, user_profile = results

        return {
            "user": user_profile if not isinstance(user_profile, Exception) else {},
            "lead": lead_state if not isinstance(lead_state, Exception) else None,
            "chat_history": chat_history if not isinstance(chat_history, Exception) else [],
            "memory": memory if not isinstance(memory, Exception) else {},
            "sop": sop if not isinstance(sop, Exception) else [],
            "calendar": calendar if not isinstance(calendar, Exception) else [],
            "aggregated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"[CONTEXT] aggregate_context error: {e}")
        return {}

async def get_chat_history(user_id: str, phone: str, limit: int = 20) -> list:
    if not phone:
        return []
    try:
        conn = await get_db()
        rows = await conn.fetch("""
            SELECT phone, message, received_at
            FROM wa_messages
            WHERE user_id = $1 AND phone = $2
            ORDER BY received_at DESC
            LIMIT $3
        """, user_id, phone, limit)
        await conn.close()
        return [dict(r) for r in reversed(rows)]
    except Exception as e:
        print(f"[CONTEXT] get_chat_history error: {e}")
        return []

async def get_long_term_memory(user_id: str, phone: str) -> dict:
    if not phone:
        return {}
    try:
        conn = await get_db()
        rows = await conn.fetch("""
            SELECT memory_key, memory_value
            FROM customer_memories
            WHERE user_id = $1 AND phone = $2
            ORDER BY updated_at DESC
            LIMIT 50
        """, user_id, phone)
        await conn.close()
        return {r['memory_key']: r['memory_value'] for r in rows}
    except Exception as e:
        print(f"[CONTEXT] get_long_term_memory error: {e}")
        return {}

async def get_workspace_sop(user_id: str) -> list:
    try:
        conn = await get_db()
        rows = await conn.fetch("""
            SELECT sop_type, content
            FROM workspace_sop
            WHERE user_id = $1
        """, user_id)
        await conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[CONTEXT] get_workspace_sop error: {e}")
        return []

async def get_active_calendar_events(user_id: str) -> list:
    try:
        conn = await get_db()
        now = datetime.utcnow()
        rows = await conn.fetch("""
            SELECT title, start_time, end_time, event_type
            FROM calendar_events
            WHERE user_id = $1
              AND start_time >= $2
              AND start_time <= $3
            ORDER BY start_time ASC
            LIMIT 10
        """, user_id, now, now + timedelta(days=7))
        await conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[CONTEXT] get_calendar_events error: {e}")
        return []

async def get_lead_state(user_id: str, phone: str) -> Optional[dict]:
    if not phone:
        return None
    try:
        conn = await get_db()
        row = await conn.fetchrow("""
            SELECT phone, name, current_state, lead_score, last_contact, follow_up_count
            FROM leads
            WHERE user_id = $1 AND phone = $2
        """, user_id, phone)
        await conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[CONTEXT] get_lead_state error: {e}")
        return None

async def get_user_profile(user_id: str) -> dict:
    try:
        conn = await get_db()
        row = await conn.fetchrow("""
            SELECT user_id, name, email, plan, business_name, business_context
            FROM users
            WHERE user_id = $1
        """, user_id)
        await conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[CONTEXT] get_user_profile error: {e}")
        return {}

async def update_lead_state(user_id: str, phone: str, new_state: str, metadata: dict = {}):
    """
    CRM State Machine — updates lead state and triggers BullMQ if READY_TO_BUY
    Lead lifecycle: NEW_LEAD → ASKED_PRICE → INTERESTED → NEGOTIATING → READY_TO_BUY → CLOSED
    """
    try:
        conn = await get_db()
        
        # Get previous state
        existing = await conn.fetchrow("""
            SELECT current_state FROM leads WHERE user_id = $1 AND phone = $2
        """, user_id, phone)
        
        previous_state = existing['current_state'] if existing else 'NEW_LEAD'
        lead_score = metadata.get('lead_score', 50)

        # Upsert lead
        await conn.execute("""
            INSERT INTO leads (user_id, phone, current_state, lead_score, last_contact, updated_at)
            VALUES ($1, $2, $3, $4, NOW(), NOW())
            ON CONFLICT (user_id, phone)
            DO UPDATE SET
                current_state = $3,
                lead_score = $4,
                last_contact = NOW(),
                updated_at = NOW()
        """, user_id, phone, new_state, lead_score)

        await conn.close()

        # Save memories
        if metadata.get('memories'):
            for key, value in metadata['memories'].items():
                await save_memory(user_id, phone, key, str(value))

        # Trigger hot lead alert if READY_TO_BUY
        if new_state == 'READY_TO_BUY' and previous_state != 'READY_TO_BUY':
            await trigger_hot_lead_alert(user_id, phone, metadata)
            print(f"[CRM] 🔥 HOT LEAD: {phone} → {new_state}")

        print(f"[CRM] Lead {phone}: {previous_state} → {new_state}")
        return {"previous_state": previous_state, "new_state": new_state}

    except Exception as e:
        print(f"[CRM] update_lead_state error: {e}")
        return None

async def save_memory(user_id: str, phone: str, key: str, value: str):
    try:
        conn = await get_db()
        await conn.execute("""
            INSERT INTO customer_memories (user_id, phone, memory_key, memory_value, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id, phone, memory_key)
            DO UPDATE SET memory_value = $4, updated_at = NOW()
        """, user_id, phone, key, value)
        await conn.close()
    except Exception as e:
        print(f"[MEMORY] save_memory error: {e}")

async def trigger_hot_lead_alert(user_id: str, phone: str, metadata: dict):
    """Push hot lead notification to ARQ queue"""
    try:
        from app.services.queue_service import get_arq_pool
        pool = await get_arq_pool()
        await pool.enqueue_job('send_hot_lead_notification', {
            'user_id': user_id,
            'phone': phone,
            'metadata': metadata,
            'timestamp': datetime.utcnow().isoformat(),
        })
    except Exception as e:
        print(f"[CRM] trigger_hot_lead_alert error: {e}")