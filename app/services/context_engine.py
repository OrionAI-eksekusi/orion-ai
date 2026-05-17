"""
APEX Parallel Context Engine - psycopg2 version
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional

def get_db():
    from app.services.database_service import get_connection
    conn, _ = get_connection()
    return conn

async def aggregate_context(user_id: str, phone: str = None) -> dict:
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
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT phone, message, received_at
            FROM wa_messages
            WHERE user_id = %s AND phone = %s
            ORDER BY received_at DESC
            LIMIT %s
        """, (user_id, phone, limit))
        rows = c.fetchall()
        conn.close()
        return [{"phone": r[0], "message": r[1], "received_at": str(r[2])} for r in reversed(rows)]
    except Exception as e:
        print(f"[CONTEXT] get_chat_history error: {e}")
        return []

async def get_long_term_memory(user_id: str, phone: str) -> dict:
    if not phone:
        return {}
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT memory_key, memory_value
            FROM customer_memories
            WHERE user_id = %s AND phone = %s
            ORDER BY updated_at DESC
            LIMIT 50
        """, (user_id, phone))
        rows = c.fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        print(f"[CONTEXT] get_long_term_memory error: {e}")
        return {}

async def get_workspace_sop(user_id: str) -> list:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT sop_type, content
            FROM workspace_sop
            WHERE user_id = %s
        """, (user_id,))
        rows = c.fetchall()
        conn.close()
        return [{"sop_type": r[0], "content": r[1]} for r in rows]
    except Exception as e:
        print(f"[CONTEXT] get_workspace_sop error: {e}")
        return []

async def get_active_calendar_events(user_id: str) -> list:
    try:
        conn = get_db()
        c = conn.cursor()
        now = datetime.utcnow()
        c.execute("""
            SELECT title, start_time, end_time, event_type
            FROM calendar_events
            WHERE user_id = %s
              AND start_time >= %s
              AND start_time <= %s
            ORDER BY start_time ASC
            LIMIT 10
        """, (user_id, now, now + timedelta(days=7)))
        rows = c.fetchall()
        conn.close()
        return [{"title": r[0], "start_time": str(r[1]), "end_time": str(r[2]), "event_type": r[3]} for r in rows]
    except Exception as e:
        print(f"[CONTEXT] get_calendar_events error: {e}")
        return []

async def get_lead_state(user_id: str, phone: str) -> Optional[dict]:
    if not phone:
        return None
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT phone, name, current_state, lead_score, last_contact, follow_up_count
            FROM leads
            WHERE user_id = %s AND phone = %s
            LIMIT 1
        """, (user_id, phone))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        return {"phone": row[0], "name": row[1], "current_state": row[2], "lead_score": row[3], "last_contact": str(row[4]), "follow_up_count": row[5]}
    except Exception as e:
        print(f"[CONTEXT] get_lead_state error: {e}")
        return None

async def get_user_profile(user_id: str) -> dict:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT user_id, name, email, plan, business_name, business_context
            FROM users
            WHERE user_id = %s
            LIMIT 1
        """, (user_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {}
        return {"user_id": row[0], "name": row[1], "email": row[2], "plan": row[3], "business_name": row[4], "business_context": row[5]}
    except Exception as e:
        print(f"[CONTEXT] get_user_profile error: {e}")
        return {}

async def update_lead_state(user_id: str, phone: str, new_state: str, metadata: dict = {}):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT current_state FROM leads WHERE user_id = %s AND phone = %s", (user_id, phone))
        row = c.fetchone()
        previous_state = row[0] if row else 'NEW_LEAD'
        lead_score = metadata.get('lead_score', 50)
        c.execute("""
            INSERT INTO leads (user_id, phone, current_state, lead_score, last_contact, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (user_id, phone)
            DO UPDATE SET current_state = %s, lead_score = %s, last_contact = NOW(), updated_at = NOW()
        """, (user_id, phone, new_state, lead_score, new_state, lead_score))
        conn.commit()
        conn.close()
        if metadata.get('memories'):
            for key, value in metadata['memories'].items():
                await save_memory(user_id, phone, key, str(value))
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
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO customer_memories (user_id, phone, memory_key, memory_value, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (user_id, phone, memory_key)
            DO UPDATE SET memory_value = %s, updated_at = NOW()
        """, (user_id, phone, key, value, value))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[MEMORY] save_memory error: {e}")

async def trigger_hot_lead_alert(user_id: str, phone: str, metadata: dict):
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
