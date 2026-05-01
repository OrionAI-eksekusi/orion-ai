import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "orion.db")

def init_memory_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS customer_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            name TEXT DEFAULT '',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            preferences TEXT DEFAULT '{}',
            history TEXT DEFAULT '[]',
            notes TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()

def get_customer_memory(phone: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM customer_memory WHERE phone=?", (phone,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "phone": row[1],
        "name": row[2],
        "first_seen": row[3],
        "last_seen": row[4],
        "message_count": row[5],
        "preferences": json.loads(row[6]),
        "history": json.loads(row[7]),
        "notes": row[8]
    }

def update_customer_memory(phone: str, message: str, reply: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    existing = get_customer_memory(phone)
    
    if not existing:
        history = json.dumps([{"msg": message, "reply": reply, "time": now}])
        c.execute('''
            INSERT INTO customer_memory (phone, first_seen, last_seen, message_count, history)
            VALUES (?, ?, ?, 1, ?)
        ''', (phone, now, now, history))
    else:
        history = json.loads(existing["history"])
        history.append({"msg": message, "reply": reply, "time": now})
        history = history[-20:]  # simpan 20 percakapan terakhir
        c.execute('''
            UPDATE customer_memory 
            SET last_seen=?, message_count=message_count+1, history=?
            WHERE phone=?
        ''', (now, json.dumps(history), phone))
    
    conn.commit()
    conn.close()

def update_customer_name(phone: str, name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE customer_memory SET name=? WHERE phone=?", (name, phone))
    conn.commit()
    conn.close()

def get_all_customers(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT phone, name, first_seen, last_seen, message_count, notes
        FROM customer_memory ORDER BY last_seen DESC LIMIT ?
    ''', (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"phone": r[0], "name": r[1], "first_seen": r[2], "last_seen": r[3], "message_count": r[4], "notes": r[5]} for r in rows]

def build_customer_context(phone: str):
    memory = get_customer_memory(phone)
    if not memory:
        return ""
    
    history_text = ""
    for h in memory["history"][-5:]:
        history_text += f"Customer: {h['msg']}\nOrion: {h['reply']}\n\n"
    
    return f"""
MEMORI CUSTOMER:
Nomor: {phone}
Nama: {memory['name'] or 'Belum diketahui'}
Pertama chat: {memory['first_seen']}
Terakhir chat: {memory['last_seen']}
Total pesan: {memory['message_count']}

Riwayat percakapan terakhir:
{history_text}

PENTING: Gunakan memori ini untuk membalas lebih personal. 
Kalau sudah kenal namanya, sapa dengan namanya.
Kalau pernah tanya produk tertentu, ingat preferensinya.
"""