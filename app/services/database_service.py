import sqlite3
import os
from datetime import datetime

DB_PATH = "orion.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS wa_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            received_at TEXT NOT NULL,
            replied INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def save_wa_message(phone: str, message: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO wa_messages (phone, message, received_at) VALUES (?, ?, ?)",
        (phone, message, datetime.now().strftime("%H:%M"))
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