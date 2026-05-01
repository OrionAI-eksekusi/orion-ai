import sqlite3
import os
import re
import json
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "orion.db")

BLOCKED_PHONES = ['status@broadcast', 'status', 'broadcast', '']

MAX_NAME_LENGTH = 30
MAX_HISTORY = 20

# ─────────────────────────────────────────────
# DB INIT
# ─────────────────────────────────────────────

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

# ─────────────────────────────────────────────
# VALIDASI
# ─────────────────────────────────────────────

def is_valid_phone(phone: str) -> bool:
    if not phone or not isinstance(phone, str):
        return False
    phone_lower = phone.lower().strip()
    for blocked in BLOCKED_PHONES:
        if blocked and blocked in phone_lower:
            return False
    if not any(c.isdigit() for c in phone):
        return False
    return True

def sanitize_name(name: str) -> str:
    if not name:
        return ''
    cleaned = re.sub(r'<[^>]*>', '', name)
    cleaned = re.sub(r"[^a-zA-Z\s.\-']", '', cleaned).strip()
    cleaned = cleaned.capitalize()
    return cleaned[:MAX_NAME_LENGTH] if cleaned else ''

# ─────────────────────────────────────────────
# EXTRACT NAMA
# ─────────────────────────────────────────────

NAME_PATTERNS = [
    r'nama\s*(?:saya|ku|gue|gw|aku|q)\s+([A-Za-z]+)',
    r'panggil\s+(?:saya|aku|gue|gw|q)\s+([A-Za-z]+)',
    r'^(?:halo[,\s]+)?(?:perkenalkan[,\s]+)?saya\s+([A-Za-z]{2,})\b',
    r'^(?:halo[,\s]+)?(?:perkenalkan[,\s]+)?aku\s+([A-Za-z]{2,})\b',
    r'^ini\s+([A-Za-z]{2,})\s+(?:kak|pak|bu|gan|sis|min|boss|bro)\b',
    r'perkenalkan[,\s]+(?:nama\s+saya\s+)?([A-Za-z]+)',
    r'^(?:hi|halo|hey)[,\s]+(?:saya|aku)\s+([A-Za-z]+)',
    r'my\s+name\s+is\s+([A-Za-z]+)',
    r'call\s+me\s+([A-Za-z]+)',
]

NOT_A_NAME = {
    'mau', 'ingin', 'minta', 'tanya', 'nanya', 'coba', 'sudah', 'lagi',
    'juga', 'belum', 'tidak', 'bisa', 'perlu', 'butuh', 'order', 'pesan',
    'beli', 'cari', 'lihat', 'tahu', 'tau', 'disini', 'sini', 'senang',
    'baik', 'ok', 'oke', 'siap', 'ada', 'ga', 'gak', 'customer', 'pelanggan',
    'pembeli', 'user', 'admin', 'bot', 'ai', 'dari', 'untuk', 'dengan',
    'yang', 'dan', 'atau', 'jika', 'kalau', 'the', 'and', 'or', 'is',
    'am', 'are', 'was', 'were', 'be'
}

def extract_name_from_message(message: str) -> str:
    if not message or len(message.strip()) < 3:
        return ''
    msg_clean = message.strip()
    msg_lower = msg_clean.lower()
    for pattern in NAME_PATTERNS:
        match = re.search(pattern, msg_lower, re.IGNORECASE)
        if match:
            start = match.start(1)
            end = match.end(1)
            name_candidate = msg_clean[start:end]
            name_lower = name_candidate.lower()
            if (name_lower not in NOT_A_NAME
                    and 2 <= len(name_candidate) <= MAX_NAME_LENGTH
                    and name_candidate.isalpha()):
                return sanitize_name(name_candidate)
    return ''

# ─────────────────────────────────────────────
# CRUD MEMORY
# ─────────────────────────────────────────────

def get_customer_memory(phone: str):
    if not is_valid_phone(phone):
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM customer_memory WHERE phone=?", (phone,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    try:
        preferences = json.loads(row[6]) if row[6] else {}
        history = json.loads(row[7]) if row[7] else []
    except (json.JSONDecodeError, TypeError):
        preferences, history = {}, []
    return {
        "phone": row[1],
        "name": row[2] or '',
        "first_seen": row[3],
        "last_seen": row[4],
        "message_count": row[5],
        "preferences": preferences,
        "history": history,
        "notes": row[8] or ''
    }

def update_customer_memory(phone: str, message: str, reply: str):
    if not is_valid_phone(phone):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    extracted_name = extract_name_from_message(message)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    try:
        c.execute("SELECT name, history, message_count FROM customer_memory WHERE phone=?", (phone,))
        row = c.fetchone()
        new_entry = {"msg": message[:500], "reply": reply[:500], "time": now}
        if not row:
            history = json.dumps([new_entry])
            c.execute('''
                INSERT INTO customer_memory (phone, name, first_seen, last_seen, message_count, history)
                VALUES (?, ?, ?, ?, 1, ?)
            ''', (phone, extracted_name, now, now, history))
        else:
            existing_name, existing_history_raw, msg_count = row
            try:
                history = json.loads(existing_history_raw) if existing_history_raw else []
            except json.JSONDecodeError:
                history = []
            history.append(new_entry)
            history = history[-MAX_HISTORY:]
            final_name = existing_name or extracted_name
            c.execute('''
                UPDATE customer_memory
                SET last_seen=?, message_count=message_count+1, history=?, name=?
                WHERE phone=?
            ''', (now, json.dumps(history), final_name, phone))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def update_customer_name(phone: str, name: str):
    if not is_valid_phone(phone):
        return
    clean_name = sanitize_name(name)
    if not clean_name:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE customer_memory SET name=? WHERE phone=?", (clean_name, phone))
    conn.commit()
    conn.close()

def get_all_customers(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT phone, name, first_seen, last_seen, message_count, notes
        FROM customer_memory
        WHERE phone NOT LIKE '%broadcast%'
        AND phone NOT LIKE '%status%'
        ORDER BY last_seen DESC LIMIT ?
    ''', (limit,))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "phone": r[0], "name": r[1] or '',
            "first_seen": r[2], "last_seen": r[3],
            "message_count": r[4], "notes": r[5] or ''
        }
        for r in rows
    ]

def build_customer_context(phone: str) -> str:
    if not is_valid_phone(phone):
        return ""
    memory = get_customer_memory(phone)
    if not memory:
        return ""
    history_text = ""
    for h in memory["history"][-5:]:
        history_text += f"Customer: {h.get('msg', '')}\nOrion: {h.get('reply', '')}\n\n"
    return f"""
MEMORI CUSTOMER:
Nomor: {phone}
Nama: {memory['name'] or 'Belum diketahui'}
Pertama chat: {memory['first_seen']}
Terakhir chat: {memory['last_seen']}
Total pesan: {memory['message_count']}

Riwayat percakapan terakhir:
{history_text.strip()}

PENTING: Gunakan memori ini untuk membalas lebih personal.
Kalau sudah kenal namanya, sapa dengan namanya.
Kalau pernah tanya produk tertentu, ingat preferensinya.
""".strip()