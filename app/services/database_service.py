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
    c.execute('''
        CREATE TABLE IF NOT EXISTS wa_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            received_at TEXT NOT NULL,
            replied INTEGER DEFAULT 0,
            follow_up_sent INTEGER DEFAULT 0,
            received_timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        )
    ''')
    # Tambah kolom baru kalau belum ada (untuk database lama)
    try:
        c.execute("ALTER TABLE wa_messages ADD COLUMN follow_up_sent INTEGER DEFAULT 0")
    except:
        pass
    try:
        c.execute("ALTER TABLE wa_messages ADD COLUMN received_timestamp TEXT")
        c.execute("UPDATE wa_messages SET received_timestamp = datetime('now') WHERE received_timestamp IS NULL")
    except:
        pass
    conn.commit()
    conn.close()

def save_wa_message(phone: str, message: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO wa_messages (phone, message, received_at, received_timestamp) VALUES (?, ?, ?, ?)",
        (phone, message, datetime.now().strftime("%H:%M"), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_wa_messages(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT phone, message, received_at, replied FROM wa_messages ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [{"phone": r[0], "message": r[1], "time": r[2], "replied": bool(r[3])} for r in rows]

def mark_replied(phone: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE wa_messages SET replied=1 WHERE phone=? AND replied=0", (phone,))
    conn.commit()
    conn.close()

def get_unreplied_messages(hours: int = 24):
    """Ambil pesan yang belum dibalas lebih dari X jam"""
    conn = sqlite33.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT phone, message, received_timestamp
        FROM wa_messages
        WHERE replied = 0
        AND follow_up_sent = 0
        AND received_timestamp IS NOT NULL
        AND (julianday('now') - julianday(received_timestamp)) * 24 >= ?
        ORDER BY received_timestamp ASC
    ''', (hours,))
    rows = c.fetchall()
    conn.close()
    return [{"phone": r[0], "message": r[1], "received_at": r[2]} for r in rows]

def mark_follow_up_sent(phone: str):
    """Tandai bahwa follow up sudah dikirim"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE wa_messages SET follow_up_sent=1 WHERE phone=? AND replied=0",
        (phone,)
    )
    conn.commit()
    conn.close()