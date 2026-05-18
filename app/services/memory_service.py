"""
APEX Memory Service
Customer memory + Personal Brain per user
Fixed: user_id isolation, connection leak, duplicate table, DB_PATH conflict
"""
import json
import os
import re
from datetime import datetime
from app.services.database_service import get_connection

MAX_NAME_LENGTH = 20
MAX_HISTORY     = 20
BLOCKED_PHONES  = {"status@broadcast", "status", "broadcast", ""}


# ─── VALIDASI ─────────────────────────────────────────────────────────────────

def is_valid_phone(phone: str) -> bool:
    if not phone or not isinstance(phone, str):
        return False
    if phone.lower().strip() in BLOCKED_PHONES:
        return False
    if not any(c.isdigit() for c in phone):
        return False
    return True


def sanitize_name(name: str) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"<[^>]*>", "", name)
    cleaned = re.sub(r"[^a-zA-Z\s.\-']", "", cleaned).strip().capitalize()
    return cleaned[:MAX_NAME_LENGTH] if cleaned else ""


# ─── EXTRACT NAMA ─────────────────────────────────────────────────────────────

NAME_PATTERNS = [
    r"nama\s*(?:saya|ku|gue|gw|aku|q)\s+([A-Za-z]+)",
    r"panggil\s+(?:saya|aku|gue|gw|q)\s+([A-Za-z]+)",
    r"^(?:halo[,\s]+)?(?:perkenalkan[,\s]+)?saya\s+([A-Za-z]{2,})\b",
    r"^(?:halo[,\s]+)?(?:perkenalkan[,\s]+)?aku\s+([A-Za-z]{2,})\b",
    r"perkenalkan[,\s]+(?:nama\s+saya\s+)?([A-Za-z]+)",
    r"^(?:hi|halo|hey)[,\s]+(?:saya|aku)\s+([A-Za-z]+)",
    r"my\s+name\s+is\s+([A-Za-z]+)",
    r"call\s+me\s+([A-Za-z]+)",
]

NOT_A_NAME = {
    "mau","ingin","minta","tanya","nanya","coba","sudah","lagi","juga",
    "belum","tidak","bisa","perlu","butuh","order","pesan","beli","cari",
    "lihat","tahu","tau","disini","sini","senang","baik","ok","oke","siap",
    "ada","ga","gak","customer","pelanggan","pembeli","user","admin","bot",
    "ai","dari","untuk","dengan","yang","dan","atau","jika","kalau",
    "the","and","or","is","am","are","was","were","be"
}


def extract_name_from_message(message: str) -> str:
    if not message or len(message.strip()) < 3:
        return ""
    msg_clean = message.strip()
    msg_lower = msg_clean.lower()
    for pattern in NAME_PATTERNS:
        match = re.search(pattern, msg_lower, re.IGNORECASE)
        if match:
            s, e = match.start(1), match.end(1)
            candidate = msg_clean[s:e]
            if (candidate.lower() not in NOT_A_NAME
                    and 2 <= len(candidate) <= MAX_NAME_LENGTH
                    and candidate.isalpha()):
                return sanitize_name(candidate)
    return ""


# ─── DB INIT ──────────────────────────────────────────────────────────────────

def init_memory_db():
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS customer_memory (
                id           SERIAL PRIMARY KEY,
                user_id      TEXT NOT NULL DEFAULT 'default',
                phone        TEXT NOT NULL,
                name         TEXT DEFAULT '',
                first_seen   TEXT NOT NULL,
                last_seen    TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                preferences  TEXT DEFAULT '{}',
                history      TEXT DEFAULT '[]',
                notes        TEXT DEFAULT '',
                UNIQUE (user_id, phone)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS personal_brain (
                id              SERIAL PRIMARY KEY,
                user_id         TEXT NOT NULL DEFAULT 'default',
                entity_name     TEXT NOT NULL,
                entity_type     TEXT DEFAULT 'contact',
                notes           TEXT DEFAULT '',
                details         TEXT DEFAULT '{}',
                follow_up_date  TEXT DEFAULT '',
                follow_up_done  INTEGER DEFAULT 0,
                follow_up_count INTEGER DEFAULT 0,
                last_contact    TEXT DEFAULT '',
                created_at      TIMESTAMP DEFAULT NOW(),
                updated_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ─── CUSTOMER MEMORY ──────────────────────────────────────────────────────────

def get_customer_memory(phone: str, user_id: str = "default") -> dict:
    if not is_valid_phone(phone):
        return {}
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT phone, name, first_seen, last_seen,
                   message_count, preferences, history, notes
            FROM customer_memory
            WHERE user_id = %s AND phone = %s
        """, (user_id, phone))
        row = c.fetchone()
        if not row:
            return {}
        try:
            preferences = json.loads(row[5]) if row[5] else {}
            history     = json.loads(row[6]) if row[6] else []
        except json.JSONDecodeError:
            preferences, history = {}, []
        return {
            "phone":         row[0],
            "name":          row[1] or "",
            "first_seen":    row[2],
            "last_seen":     row[3],
            "message_count": row[4],
            "preferences":   preferences,
            "history":       history,
            "notes":         row[7] or "",
        }
    finally:
        conn.close()


def update_customer_memory(phone: str, message: str, reply: str, user_id: str = "default"):
    if not is_valid_phone(phone):
        return
    now            = datetime.now().strftime("%Y-%m-%d %H:%M")
    extracted_name = extract_name_from_message(message)
    new_entry      = {"msg": message[:500], "reply": reply[:500], "time": now}

    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT name, history, message_count
            FROM customer_memory
            WHERE user_id = %s AND phone = %s
        """, (user_id, phone))
        row = c.fetchone()

        if not row:
            c.execute("""
                INSERT INTO customer_memory
                    (user_id, phone, name, first_seen, last_seen, message_count, history)
                VALUES (%s, %s, %s, %s, %s, 1, %s)
            """, (user_id, phone, extracted_name, now, now, json.dumps([new_entry])))
        else:
            existing_name, existing_history_raw, _ = row
            try:
                history = json.loads(existing_history_raw) if existing_history_raw else []
            except json.JSONDecodeError:
                history = []
            history.append(new_entry)
            history    = history[-MAX_HISTORY:]
            final_name = existing_name or extracted_name
            c.execute("""
                UPDATE customer_memory
                SET last_seen     = %s,
                    message_count = message_count + 1,
                    history       = %s,
                    name          = %s
                WHERE user_id = %s AND phone = %s
            """, (now, json.dumps(history), final_name, user_id, phone))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[MEMORY] update_customer_memory error: {e}")
    finally:
        conn.close()


def update_customer_name(phone: str, name: str, user_id: str = "default"):
    if not is_valid_phone(phone):
        return
    clean = sanitize_name(name)
    if not clean:
        return
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE customer_memory SET name = %s
            WHERE user_id = %s AND phone = %s
        """, (clean, user_id, phone))
        conn.commit()
    finally:
        conn.close()


def get_all_customers(user_id: str = "default", limit: int = 50) -> list:
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT phone, name, first_seen, last_seen, message_count, notes
            FROM customer_memory
            WHERE user_id = %s
              AND phone NOT LIKE '%broadcast%'
              AND phone NOT LIKE '%status%'
            ORDER BY last_seen DESC
            LIMIT %s
        """, (user_id, limit))
        rows = c.fetchall()
        return [{
            "phone":         r[0],
            "name":          r[1] or "",
            "first_seen":    r[2],
            "last_seen":     r[3],
            "message_count": r[4],
            "notes":         r[5] or "",
        } for r in rows]
    finally:
        conn.close()


def build_customer_context(phone: str, user_id: str = "default") -> str:
    if not is_valid_phone(phone):
        return ""
    memory = get_customer_memory(phone, user_id)
    if not memory:
        return ""
    history_text = "\n\n".join([
        f"Customer: {h.get('msg','')}\nOrion: {h.get('reply','')}"
        for h in memory["history"][-5:]
    ])
    return f"""MEMORI CUSTOMER:
Nomor: {phone}
Nama: {memory['name'] or 'Belum diketahui'}
Pertama chat: {memory['first_seen']}
Terakhir chat: {memory['last_seen']}
Total pesan: {memory['message_count']}

Riwayat terakhir:
{history_text}""".strip()


# ─── PERSONAL BRAIN ───────────────────────────────────────────────────────────

def save_brain_entry(user_id: str, entity_name: str, notes: str,
                     entity_type: str = "contact", details: dict = {},
                     follow_up_date: str = "") -> bool:
    try:
        now  = datetime.now().isoformat()
        ts   = datetime.now().strftime("%d/%m/%Y %H:%M")
        conn, _ = get_connection()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT id, notes FROM personal_brain
                WHERE user_id = %s AND entity_name ILIKE %s
            """, (user_id, f"%{entity_name}%"))
            row = c.fetchone()

            if row:
                new_notes = f"{row[1] or ''}\n[{ts}] {notes}".strip()
                c.execute("""
                    UPDATE personal_brain SET
                        notes          = %s,
                        details        = %s,
                        follow_up_date = CASE WHEN %s != '' THEN %s ELSE follow_up_date END,
                        follow_up_done = CASE WHEN %s != '' THEN 0 ELSE follow_up_done END,
                        updated_at     = %s
                    WHERE id = %s
                """, (new_notes, json.dumps(details),
                      follow_up_date, follow_up_date,
                      follow_up_date, now, row[0]))
            else:
                c.execute("""
                    INSERT INTO personal_brain
                        (user_id, entity_name, entity_type, notes, details,
                         follow_up_date, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, entity_name, entity_type,
                      f"[{ts}] {notes}", json.dumps(details),
                      follow_up_date, now, now))

            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"[BRAIN] save_brain_entry error: {e}")
        return False


def get_brain_entry(user_id: str, entity_name: str) -> dict:
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT entity_name, entity_type, notes, details,
                   follow_up_date, follow_up_count, last_contact, created_at
            FROM personal_brain
            WHERE user_id = %s AND entity_name ILIKE %s
            ORDER BY updated_at DESC LIMIT 1
        """, (user_id, f"%{entity_name}%"))
        row = c.fetchone()
        if not row:
            return {}
        return {
            "name":           row[0], "type":           row[1],
            "notes":          row[2], "details":        row[3],
            "follow_up_date": row[4], "follow_up_count": row[5] or 0,
            "last_contact":   row[6] or "", "created_at": row[7],
        }
    finally:
        conn.close()


def get_all_brain_entries(user_id: str) -> list:
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT entity_name, entity_type, notes, follow_up_date,
                   follow_up_done, last_contact, updated_at
            FROM personal_brain
            WHERE user_id = %s
            ORDER BY updated_at DESC
        """, (user_id,))
        return [{
            "name":           r[0], "type":         r[1],
            "notes":          r[2], "follow_up_date": r[3],
            "follow_up_done": bool(r[4]),
            "last_contact":   r[5] or "", "updated_at": r[6],
        } for r in c.fetchall()]
    finally:
        conn.close()


def get_pending_follow_ups(user_id: str) -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT entity_name, entity_type, notes, follow_up_date, follow_up_count
            FROM personal_brain
            WHERE user_id = %s
              AND follow_up_done = 0
              AND follow_up_date != ''
              AND follow_up_date <= %s
              AND follow_up_count < 2
            ORDER BY follow_up_date ASC
        """, (user_id, today))
        return [{
            "name":           r[0], "type":           r[1],
            "notes":          r[2], "follow_up_date": r[3],
            "follow_up_count": r[4],
        } for r in c.fetchall()]
    finally:
        conn.close()


def mark_brain_follow_up_sent(user_id: str, entity_name: str):
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("""
            UPDATE personal_brain SET
                follow_up_count = follow_up_count + 1,
                follow_up_done  = CASE WHEN follow_up_count + 1 >= 2 THEN 1 ELSE 0 END,
                last_contact    = %s,
                updated_at      = %s
            WHERE user_id = %s AND entity_name ILIKE %s
        """, (now, now, user_id, f"%{entity_name}%"))
        conn.commit()
    finally:
        conn.close()


def search_brain(user_id: str, keyword: str) -> list:
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT entity_name, entity_type, notes, follow_up_date, updated_at
            FROM personal_brain
            WHERE user_id = %s
              AND (entity_name ILIKE %s OR notes ILIKE %s)
            ORDER BY updated_at DESC LIMIT 5
        """, (user_id, f"%{keyword}%", f"%{keyword}%"))
        return [{
            "name":           r[0], "type":           r[1],
            "notes":          r[2], "follow_up_date": r[3],
            "updated_at":     r[4],
        } for r in c.fetchall()]
    finally:
        conn.close()
