import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "orion.db")

def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── Tabel WA Messages ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS wa_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            received_at TEXT NOT NULL,
            replied INTEGER DEFAULT 0,
            follow_up_sent INTEGER DEFAULT 0,
            follow_up_count INTEGER DEFAULT 0,
            received_timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        )
    ''')

    # ── Tabel User Profiles ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            city TEXT DEFAULT 'Jakarta',
            gmail_token TEXT DEFAULT '',
            fcm_token TEXT DEFAULT '',
            briefing_hour INTEGER DEFAULT 6,
            timezone TEXT DEFAULT 'Asia/Jakarta',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    # ── Tabel FCM Tokens ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS fcm_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ── Tabel Personal Brain ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS personal_brain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            entity_name TEXT NOT NULL,
            entity_type TEXT DEFAULT 'contact',
            notes TEXT DEFAULT '',
            details TEXT DEFAULT '{}',
            follow_up_date TEXT DEFAULT '',
            follow_up_done INTEGER DEFAULT 0,
            follow_up_count INTEGER DEFAULT 0,
            last_contact TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    # ── Tabel Follow Up Tracker ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS follow_up_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            contact_phone TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            contact_name TEXT DEFAULT '',
            channel TEXT DEFAULT 'wa',
            follow_up_count INTEGER DEFAULT 0,
            last_follow_up TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    # Migration
    migrations = [
        "ALTER TABLE wa_messages ADD COLUMN follow_up_sent INTEGER DEFAULT 0",
        "ALTER TABLE wa_messages ADD COLUMN follow_up_count INTEGER DEFAULT 0",
        "ALTER TABLE wa_messages ADD COLUMN received_timestamp TEXT",
        "ALTER TABLE wa_messages ADD COLUMN user_id TEXT DEFAULT 'default'",
    ]
    for m in migrations:
        try:
            c.execute(m)
        except:
            pass

    try:
        c.execute("UPDATE wa_messages SET received_timestamp = datetime('now') WHERE received_timestamp IS NULL")
    except:
        pass

    conn.commit()
    conn.close()


# ── User Profile Functions ─────────────────────────────
def save_user_profile(user_id: str, name: str, email: str, phone: str,
                       city: str = "Jakarta", briefing_hour: int = 6):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO user_profiles (user_id, name, email, phone, city, briefing_hour, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            email=excluded.email,
            phone=excluded.phone,
            city=excluded.city,
            briefing_hour=excluded.briefing_hour,
            updated_at=excluded.updated_at
    ''', (user_id, name, email, phone, city, briefing_hour, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_user_profile(user_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT user_id, name, email, phone, city, briefing_hour, fcm_token, gmail_token
        FROM user_profiles WHERE user_id = ?
    ''', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return {}
    return {
        "user_id": row[0], "name": row[1], "email": row[2],
        "phone": row[3], "city": row[4], "briefing_hour": row[5],
        "fcm_token": row[6], "gmail_token": row[7]
    }


def get_all_active_users() -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT user_id, name, email, phone, city, briefing_hour, fcm_token, gmail_token
        FROM user_profiles WHERE is_active = 1
    ''')
    rows = c.fetchall()
    conn.close()
    return [{
        "user_id": r[0], "name": r[1], "email": r[2],
        "phone": r[3], "city": r[4], "briefing_hour": r[5],
        "fcm_token": r[6], "gmail_token": r[7]
    } for r in rows]


def update_user_fcm_token(user_id: str, fcm_token: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE user_profiles SET fcm_token = ?, updated_at = ?
        WHERE user_id = ?
    ''', (fcm_token, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def update_user_gmail_token(user_id: str, gmail_token: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE user_profiles SET gmail_token = ?, updated_at = ?
        WHERE user_id = ?
    ''', (gmail_token, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


# ── WA Message Functions ───────────────────────────────
def save_wa_message(phone: str, message: str, user_id: str = 'default'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO wa_messages (user_id, phone, message, received_at, received_timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, phone, message, datetime.now().strftime("%H:%M"), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_wa_messages(limit=10, user_id: str = 'default'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT phone, message, received_at, replied FROM wa_messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return [{"phone": r[0], "message": r[1], "time": r[2], "replied": bool(r[3])} for r in rows]


def mark_replied(phone: str, user_id: str = 'default'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE wa_messages SET replied=1 WHERE phone=? AND user_id=? AND replied=0",
        (phone, user_id)
    )
    conn.commit()
    conn.close()


def get_unreplied_messages(hours: int = 24, user_id: str = 'default'):
    """Ambil pesan belum dibalas — max follow up 2x"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT phone, message, received_timestamp, follow_up_count
        FROM wa_messages
        WHERE user_id = ?
        AND replied = 0
        AND follow_up_count < 2
        AND received_timestamp IS NOT NULL
        AND (julianday('now') - julianday(received_timestamp)) * 24 >= ?
        ORDER BY received_timestamp ASC
    ''', (user_id, hours))
    rows = c.fetchall()
    conn.close()
    return [{"phone": r[0], "message": r[1], "received_at": r[2], "follow_up_count": r[3]} for r in rows]


def mark_follow_up_sent(phone: str, user_id: str = 'default'):
    """Tandai follow up terkirim — increment counter"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE wa_messages 
        SET follow_up_sent=1, 
            follow_up_count=follow_up_count+1
        WHERE phone=? AND user_id=? AND replied=0
    ''', (phone, user_id))
    conn.commit()
    conn.close()


def get_follow_up_count(phone: str, user_id: str = 'default') -> int:
    """Cek sudah berapa kali follow up ke nomor ini"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT MAX(follow_up_count) FROM wa_messages
            WHERE phone=? AND user_id=?
        ''', (phone, user_id))
        row = c.fetchone()
        conn.close()
        return row[0] or 0
    except:
        return 0


# ── Personal Brain Functions ───────────────────────────
def save_brain_entry(user_id: str, entity_name: str, notes: str,
                      entity_type: str = 'contact', details: dict = {},
                      follow_up_date: str = ''):
    """Simpan atau update entri di Personal Brain"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO personal_brain 
            (user_id, entity_name, entity_type, notes, details, follow_up_date, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
    ''', (user_id, entity_name, entity_type, notes,
          json_dumps(details), follow_up_date, datetime.now().isoformat()))

    # Kalau sudah ada → update
    c.execute('''
        UPDATE personal_brain SET
            notes = notes || char(10) || ?,
            details = ?,
            follow_up_date = CASE WHEN ? != '' THEN ? ELSE follow_up_date END,
            updated_at = ?
        WHERE user_id = ? AND entity_name = ? AND id != last_insert_rowid()
    ''', (notes, json_dumps(details), follow_up_date, follow_up_date,
          datetime.now().isoformat(), user_id, entity_name))

    conn.commit()
    conn.close()


def get_brain_entry(user_id: str, entity_name: str) -> dict:
    """Cari entri di Personal Brain"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT entity_name, entity_type, notes, details, 
               follow_up_date, follow_up_count, last_contact, created_at
        FROM personal_brain
        WHERE user_id = ? AND entity_name LIKE ?
        ORDER BY updated_at DESC LIMIT 1
    ''', (user_id, f'%{entity_name}%'))
    row = c.fetchone()
    conn.close()
    if not row:
        return {}
    return {
        "name": row[0], "type": row[1], "notes": row[2],
        "details": row[3], "follow_up_date": row[4],
        "follow_up_count": row[5], "last_contact": row[6],
        "created_at": row[7]
    }


def get_all_brain_entries(user_id: str) -> list:
    """Ambil semua entri Personal Brain"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT entity_name, entity_type, notes, follow_up_date, 
               follow_up_done, last_contact, updated_at
        FROM personal_brain
        WHERE user_id = ?
        ORDER BY updated_at DESC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{
        "name": r[0], "type": r[1], "notes": r[2],
        "follow_up_date": r[3], "follow_up_done": bool(r[4]),
        "last_contact": r[5], "updated_at": r[6]
    } for r in rows]


def get_pending_follow_ups(user_id: str) -> list:
    """Ambil follow up yang sudah jatuh tempo"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT entity_name, entity_type, notes, follow_up_date, follow_up_count
        FROM personal_brain
        WHERE user_id = ?
        AND follow_up_done = 0
        AND follow_up_date != ''
        AND follow_up_date <= ?
        AND follow_up_count < 2
        ORDER BY follow_up_date ASC
    ''', (user_id, today))
    rows = c.fetchall()
    conn.close()
    return [{
        "name": r[0], "type": r[1], "notes": r[2],
        "follow_up_date": r[3], "follow_up_count": r[4]
    } for r in rows]


def mark_brain_follow_up_done(user_id: str, entity_name: str):
    """Tandai follow up selesai"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE personal_brain SET
            follow_up_done = 1,
            follow_up_count = follow_up_count + 1,
            last_contact = ?,
            updated_at = ?
        WHERE user_id = ? AND entity_name = ?
    ''', (datetime.now().isoformat(), datetime.now().isoformat(),
          user_id, entity_name))
    conn.commit()
    conn.close()


def json_dumps(data: dict) -> str:
    try:
        import json
        return json.dumps(data, ensure_ascii=False)
    except:
        return '{}'


# ── FCM Token Functions ────────────────────────────────
def save_fcm_token_db(token: str, user_id: str = 'default'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS fcm_tokens
        (id INTEGER PRIMARY KEY, user_id TEXT, token TEXT UNIQUE,
         created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
    ''')
    c.execute(
        "INSERT OR REPLACE INTO fcm_tokens (user_id, token) VALUES (?, ?)",
        (user_id, token)
    )
    c.execute(
        "UPDATE user_profiles SET fcm_token=? WHERE user_id=?",
        (token, user_id)
    )
    conn.commit()
    conn.close()


def get_fcm_token_db(user_id: str = 'default') -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT token FROM fcm_tokens WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = c.fetchone()
        conn.close()
        return row[0] if row else ""
    except:
        return ""