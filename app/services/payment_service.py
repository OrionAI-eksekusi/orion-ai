import sqlite3
import os
import json
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "orion.db")


def init_payment_db():
    """Inisialisasi tabel payment/invoice"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            invoice_number TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            customer_phone TEXT DEFAULT '',
            customer_email TEXT DEFAULT '',
            amount REAL NOT NULL,
            description TEXT DEFAULT '',
            due_date TEXT NOT NULL,
            status TEXT DEFAULT 'unpaid',
            reminder_count INTEGER DEFAULT 0,
            paid_at TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    # ✅ FIX: Hapus semua data test / dummy saat init
    # Hapus invoice user "default" yang merupakan data test developer
    c.execute("DELETE FROM invoices WHERE user_id = 'default'")

    conn.commit()
    conn.close()


def create_invoice(
    user_id: str,
    customer_name: str,
    amount: float,
    due_date: str,
    description: str = "",
    customer_phone: str = "",
    customer_email: str = "",
) -> dict:
    """Buat invoice baru"""
    # ✅ FIX: Tolak user_id = default, wajib user_id unik
    if not user_id or user_id.strip() == "" or user_id == "default":
        raise ValueError("user_id tidak valid. User harus login dulu.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    invoice_number = f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id[:4].upper()}"

    c.execute('''
        INSERT INTO invoices
            (user_id, invoice_number, customer_name, customer_phone,
             customer_email, amount, description, due_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, invoice_number, customer_name, customer_phone,
          customer_email, amount, description, due_date))

    conn.commit()
    conn.close()

    return {
        "invoice_number": invoice_number,
        "customer_name": customer_name,
        "amount": amount,
        "due_date": due_date,
        "status": "unpaid"
    }


def get_unpaid_invoices(user_id: str) -> list:
    """Ambil invoice yang belum dibayar — wajib user_id valid"""
    # ✅ FIX: user_id default tidak boleh dapat data apapun
    if not user_id or user_id == "default":
        return []

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT invoice_number, customer_name, customer_phone,
               customer_email, amount, description, due_date,
               reminder_count, created_at
        FROM invoices
        WHERE user_id = ?
        AND status = 'unpaid'
        AND reminder_count < 3
        ORDER BY due_date ASC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{
        "invoice_number": r[0],
        "customer_name": r[1],
        "customer_phone": r[2],
        "customer_email": r[3],
        "amount": r[4],
        "description": r[5],
        "due_date": r[6],
        "reminder_count": r[7],
        "created_at": r[8]
    } for r in rows]


def get_due_invoices(user_id: str) -> list:
    """Ambil invoice yang sudah jatuh tempo hari ini"""
    # ✅ FIX: user_id default tidak boleh dapat data apapun
    if not user_id or user_id == "default":
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT invoice_number, customer_name, customer_phone,
               customer_email, amount, description, due_date, reminder_count
        FROM invoices
        WHERE user_id = ?
        AND status = 'unpaid'
        AND due_date <= ?
        AND reminder_count < 3
        ORDER BY due_date ASC
    ''', (user_id, today))
    rows = c.fetchall()
    conn.close()
    return [{
        "invoice_number": r[0],
        "customer_name": r[1],
        "customer_phone": r[2],
        "customer_email": r[3],
        "amount": r[4],
        "description": r[5],
        "due_date": r[6],
        "reminder_count": r[7]
    } for r in rows]


def mark_invoice_paid(invoice_number: str, user_id: str) -> bool:
    """Tandai invoice sebagai lunas — wajib user_id valid"""
    if not user_id or user_id == "default":
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE invoices SET
                status = 'paid',
                paid_at = ?,
                updated_at = ?
            WHERE invoice_number = ? AND user_id = ?
        ''', (datetime.now().isoformat(), datetime.now().isoformat(),
              invoice_number, user_id))
        affected = c.rowcount
        conn.commit()
        conn.close()
        # ✅ FIX: Return False kalau tidak ada row yang diupdate
        return affected > 0
    except Exception as e:
        print(f"[PAYMENT ERROR] {e}")
        return False


def increment_reminder_count(invoice_number: str, user_id: str):
    """Increment reminder count"""
    if not user_id or user_id == "default":
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE invoices SET
            reminder_count = reminder_count + 1,
            updated_at = ?
        WHERE invoice_number = ? AND user_id = ?
    ''', (datetime.now().isoformat(), invoice_number, user_id))
    conn.commit()
    conn.close()


def get_all_invoices(user_id: str) -> list:
    """Ambil semua invoice milik user — wajib user_id valid"""
    # ✅ FIX: Kalau user_id default atau kosong, return kosong
    if not user_id or user_id == "default":
        return []

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT invoice_number, customer_name, customer_phone,
               amount, description, due_date, status, reminder_count, created_at
        FROM invoices
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{
        "invoice_number": r[0],
        "customer_name": r[1],
        "customer_phone": r[2],
        "amount": r[3],
        "description": r[4],
        "due_date": r[5],
        "status": r[6],
        "reminder_count": r[7],
        "created_at": r[8]
    } for r in rows]


def delete_test_data():
    """✅ Utility: Hapus semua data test dari DB production"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM invoices WHERE user_id = 'default'")
    deleted = c.rowcount
    conn.commit()
    conn.close()
    print(f"[CLEANUP] Hapus {deleted} data test dari invoices")
    return deleted


async def extract_invoice_from_command(message: str) -> dict:
    """Extract info invoice dari perintah user pakai AI"""
    from app.services.ai_provider import call_llm
    from datetime import datetime, timedelta

    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    system_prompt = f"""Dari perintah berikut, ekstrak informasi invoice dalam JSON:
{{
    "customer_name": "nama customer",
    "customer_phone": "nomor WA customer (62xxx) jika ada, kosong jika tidak",
    "customer_email": "email customer jika ada, kosong jika tidak",
    "amount": 0,
    "description": "deskripsi tagihan",
    "due_date": "tanggal jatuh tempo format YYYY-MM-DD"
}}

Hari ini: {today}
Besok: {tomorrow}

Contoh:
- "tagih Pak Budi 500rb besok" → due_date: {tomorrow}
- "invoice Bu Sari 1.5 juta minggu depan" → due_date: 7 hari dari sekarang
- "nagih 081234 250000 hari ini" → customer_phone: 62081234, due_date: {today}

PENTING: Jika tidak ada nama customer yang jelas, kembalikan customer_name sebagai string kosong "".
Jika tidak ada nominal yang jelas, kembalikan amount sebagai 0.

Respond HANYA dengan JSON."""

    try:
        response = await call_llm(system_prompt, message)
        clean = response.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except Exception as e:
        print(f"[INVOICE EXTRACT ERROR] {e}")
        return {
            "customer_name": "",
            "customer_phone": "",
            "customer_email": "",
            "amount": 0,
            "description": "Tagihan",
            "due_date": tomorrow
        }


def format_amount(amount: float) -> str:
    """Format angka ke Rupiah"""
    return f"Rp {amount:,.0f}".replace(",", ".")