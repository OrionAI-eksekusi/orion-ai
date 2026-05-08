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
            received_timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        )
    ''')

    # ── Tabel User Profiles (untuk multi user) ──
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

    # ── Tabel FCM Tokens per user ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS fcm_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Migration — tambah kolom baru kalau belum ada
    migrations = [
        "ALTER TABLE wa_messages ADD COLUMN follow_up_sent INTEGER DEFAULT 0",
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
    """Simpan atau update profil user"""
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
    """Ambil profil user berdasarkan user_id"""
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
    """Ambil semua user aktif — untuk scheduler briefing"""
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
    """Update FCM token user"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE user_profiles SET fcm_token = ?, updated_at = ?
        WHERE user_id = ?
    ''', (fcm_token, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def update_user_gmail_token(user_id: str, gmail_token: str):
    """Update Gmail token user"""
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
    """Ambil pesan yang belum dibalas lebih dari X jam"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT phone, message, received_timestamp
        FROM wa_messages
        WHERE user_id = ?
        AND replied = 0
        AND follow_up_sent = 0
        AND received_timestamp IS NOT NULL
        AND (julianday('now') - julianday(received_timestamp)) * 24 >= ?
        ORDER BY received_timestamp ASC
    ''', (user_id, hours))
    rows = c.fetchall()
    conn.close()
    return [{"phone": r[0], "message": r[1], "received_at": r[2]} for r in rows]


def mark_follow_up_sent(phone: str, user_id: str = 'default'):
    """Tandai bahwa follow up sudah dikirim"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE wa_messages SET follow_up_sent=1 WHERE phone=? AND user_id=? AND replied=0",
        (phone, user_id)
    )
    conn.commit()
    conn.close()


# ── FCM Token Functions ────────────────────────────────
def save_fcm_token_db(token: str, user_id: str = 'default'):
    """Simpan FCM token per user"""
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
    # Update juga di user_profiles
    c.execute(
        "UPDATE user_profiles SET fcm_token=? WHERE user_id=?",
        (token, user_id)
    )
    conn.commit()
    conn.close()


def get_fcm_token_db(user_id: str = 'default') -> str:
    """Ambil FCM token per user"""
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