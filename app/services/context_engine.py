"""
APEX Parallel Context Engine
Fixed: asyncio.to_thread untuk blocking DB, connection leak, calendar live API
"""
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional


def _get_conn():
    from app.services.database_service import get_connection
    conn, _ = get_connection()
    return conn


# ─── AGGREGATE ────────────────────────────────────────────────────────────────

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
            "user":         user_profile  if not isinstance(user_profile,  Exception) else {},
            "lead":         lead_state    if not isinstance(lead_state,    Exception) else None,
            "chat_history": chat_history  if not isinstance(chat_history,  Exception) else [],
            "memory":       memory        if not isinstance(memory,        Exception) else {},
            "sop":          sop           if not isinstance(sop,           Exception) else [],
            "calendar":     calendar      if not isinstance(calendar,      Exception) else [],
            "aggregated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"[CONTEXT] aggregate_context error: {e}")
        return {}


# ─── CHAT HISTORY ─────────────────────────────────────────────────────────────

async def get_chat_history(user_id: str, phone: str, limit: int = 20) -> list:
    if not phone:
        return []

    def _query():
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT phone, message, received_at
                FROM wa_messages
                WHERE user_id = %s AND phone = %s
                ORDER BY received_at DESC
                LIMIT %s
            """, (user_id, phone, limit))
            rows = c.fetchall()
            return [{"phone": r[0], "message": r[1], "received_at": str(r[2])} for r in reversed(rows)]
        finally:
            conn.close()

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        print(f"[CONTEXT] get_chat_history error: {e}")
        return []


# ─── LONG TERM MEMORY ─────────────────────────────────────────────────────────

async def get_long_term_memory(user_id: str, phone: str) -> dict:
    if not phone:
        return {}

    def _query():
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT memory_key, memory_value
                FROM customer_memories
                WHERE user_id = %s AND phone = %s
                ORDER BY updated_at DESC
                LIMIT 50
            """, (user_id, phone))
            rows = c.fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            conn.close()

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        print(f"[CONTEXT] get_long_term_memory error: {e}")
        return {}


# ─── WORKSPACE SOP ────────────────────────────────────────────────────────────

async def get_workspace_sop(user_id: str) -> list:
    def _query():
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT sop_type, content
                FROM workspace_sop
                WHERE user_id = %s
                LIMIT 20
            """, (user_id,))
            rows = c.fetchall()
            return [{"sop_type": r[0], "content": r[1]} for r in rows]
        finally:
            conn.close()

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        print(f"[CONTEXT] get_workspace_sop error: {e}")
        return []


# ─── CALENDAR EVENTS (Google Calendar API langsung) ───────────────────────────

async def get_active_calendar_events(user_id: str) -> list:
    def _query():
        try:
            from app.services.calendar_service import get_upcoming_events
            result = get_upcoming_events(user_id, max_results=5)
            if result.get("reauth_required"):
                return []
            events = result.get("events", [])
            simplified = []
            for e in events:
                start = e.get("start", {})
                simplified.append({
                    "title": e.get("summary", ""),
                    "start_time": start.get("dateTime") or start.get("date", ""),
                    "event_type": e.get("eventType", "default"),
                })
            return simplified
        except Exception as e:
            print(f"[CONTEXT] calendar API error: {e}")
            return []

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        print(f"[CONTEXT] get_active_calendar_events error: {e}")
        return []


# ─── LEAD STATE ───────────────────────────────────────────────────────────────

async def get_lead_state(user_id: str, phone: str) -> Optional[dict]:
    if not phone:
        return None

    def _query():
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT phone, name, current_state, lead_score, last_contact, follow_up_count
                FROM leads
                WHERE user_id = %s AND phone = %s
                LIMIT 1
            """, (user_id, phone))
            row = c.fetchone()
            if not row:
                return None
            return {
                "phone":          row[0],
                "name":           row[1],
                "current_state":  row[2],
                "lead_score":     row[3],
                "last_contact":   str(row[4]),
                "follow_up_count": row[5],
            }
        finally:
            conn.close()

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        print(f"[CONTEXT] get_lead_state error: {e}")
        return None


# ─── USER PROFILE ─────────────────────────────────────────────────────────────

async def get_user_profile(user_id: str) -> dict:
    def _query():
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, name, email, plan, business_name, business_context
                FROM users
                WHERE user_id = %s
                LIMIT 1
            """, (user_id,))
            row = c.fetchone()
            if not row:
                return {}
            return {
                "user_id":          row[0],
                "name":             row[1],
                "email":            row[2],
                "plan":             row[3],
                "business_name":    row[4],
                "business_context": row[5],
            }
        finally:
            conn.close()

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        print(f"[CONTEXT] get_user_profile error: {e}")
        return {}


# ─── UPDATE LEAD STATE + CRM MACHINE ──────────────────────────────────────────

async def update_lead_state(user_id: str, phone: str, new_state: str, metadata: dict = {}):
    def _upsert():
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT current_state FROM leads
                WHERE user_id = %s AND phone = %s
            """, (user_id, phone))
            row = c.fetchone()
            previous_state = row[0] if row else "NEW_LEAD"

            lead_score = metadata.get("lead_score", 50)
            c.execute("""
                INSERT INTO leads (user_id, phone, current_state, lead_score, last_contact, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id, phone)
                DO UPDATE SET
                    current_state = %s,
                    lead_score    = %s,
                    last_contact  = NOW(),
                    updated_at    = NOW()
            """, (user_id, phone, new_state, lead_score, new_state, lead_score))
            conn.commit()
            return previous_state
        finally:
            conn.close()

    try:
        previous_state = await asyncio.to_thread(_upsert)

        if metadata.get("memories"):
            await asyncio.gather(*[
                save_memory(user_id, phone, k, str(v))
                for k, v in metadata["memories"].items()
            ])

        if new_state == "READY_TO_BUY" and previous_state != "READY_TO_BUY":
            await trigger_hot_lead_alert(user_id, phone, metadata)
            print(f"[CRM] 🔥 HOT LEAD: {phone} → {new_state}")

        print(f"[CRM] Lead {phone}: {previous_state} → {new_state}")
        return {"previous_state": previous_state, "new_state": new_state}

    except Exception as e:
        print(f"[CRM] update_lead_state error: {e}")
        return None


# ─── SAVE MEMORY ──────────────────────────────────────────────────────────────

async def save_memory(user_id: str, phone: str, key: str, value: str):
    def _upsert():
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO customer_memories (user_id, phone, memory_key, memory_value, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, phone, memory_key)
                DO UPDATE SET memory_value = %s, updated_at = NOW()
            """, (user_id, phone, key, value, value))
            conn.commit()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_upsert)
    except Exception as e:
        print(f"[MEMORY] save_memory error: {e}")


# ─── HOT LEAD ALERT ───────────────────────────────────────────────────────────

async def trigger_hot_lead_alert(user_id: str, phone: str, metadata: dict):
    try:
        from app.services.queue_service import get_arq_pool
        pool = await get_arq_pool()
        await pool.enqueue_job("process_wa_message", {
            "user_id":   user_id,
            "phone":     phone,
            "metadata":  metadata,
            "timestamp": datetime.utcnow().isoformat(),
            "event":     "HOT_LEAD",
        })
    except Exception as e:
        print(f"[CRM] trigger_hot_lead_alert error: {e}")
