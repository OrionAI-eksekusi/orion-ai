from app.services.database_service import get_connection, DB_PATH
import sqlite3
import os
import json
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "orion.db")


def init_payment_db():
    """Inisialisasi tabel payment/invoice"""
    conn, _db_type = get_connection()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY,
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
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    ''')

    # Hapus data test user default
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
    if not user_id or user_id.strip() == "" or user_id == "default":
        raise ValueError("user_id tidak valid. User harus login dulu.")

    conn, _db_type = get_connection()
    c = conn.cursor()

    invoice_number = f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id[:4].upper()}"

    c.execute('''
        INSERT INTO invoices
            (user_id, invoice_number, customer_name, customer_phone,
             customer_email, amount, description, due_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (user_id, invoice_number, customer_name, customer_phone,
          customer_email, amount, description, due_date))

    conn.commit()
    conn.close()

    return {
        "invoice_number": invoice_number,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "amount": amount,
        "due_date": due_date,
        "description": description,
        "status": "unpaid"
    }


def get_invoice_by_number(invoice_number: str, user_id: str) -> dict:
    """Ambil 1 invoice by nomor invoice"""
    if not user_id or user_id == "default":
        return {}
    conn, _db_type = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT invoice_number, customer_name, customer_phone,
               customer_email, amount, description, due_date,
               status, reminder_count
        FROM invoices
        WHERE invoice_number = %s AND user_id = %s
    ''', (invoice_number, user_id))
    row = c.fetchone()
    conn.close()
    if not row:
        return {}
    return {
        "invoice_number": row[0],
        "customer_name": row[1],
        "customer_phone": row[2],
        "customer_email": row[3],
        "amount": row[4],
        "description": row[5],
        "due_date": row[6],
        "status": row[7],
        "reminder_count": row[8]
    }


def get_unpaid_invoices(user_id: str) -> list:
    """Ambil invoice yang belum dibayar"""
    if not user_id or user_id == "default":
        return []
    conn, _db_type = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT invoice_number, customer_name, customer_phone,
               customer_email, amount, description, due_date,
               reminder_count, created_at
        FROM invoices
        WHERE user_id = %s
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
    if not user_id or user_id == "default":
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    conn, _db_type = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT invoice_number, customer_name, customer_phone,
               customer_email, amount, description, due_date, reminder_count
        FROM invoices
        WHERE user_id = %s
        AND status = 'unpaid'
        AND due_date <= %s
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
    """Tandai invoice sebagai lunas"""
    if not user_id or user_id == "default":
        return False
    try:
        conn, _db_type = get_connection()
        c = conn.cursor()
        c.execute('''
            UPDATE invoices SET
                status = 'paid',
                paid_at = %s,
                updated_at = %s
            WHERE invoice_number = %s AND user_id = %s
        ''', (datetime.now().isoformat(), datetime.now().isoformat(),
              invoice_number, user_id))
        affected = c.rowcount
        conn.commit()
        conn.close()
        return affected > 0
    except Exception as e:
        print(f"[PAYMENT ERROR] {e}")
        return False


def increment_reminder_count(invoice_number: str, user_id: str):
    """Increment reminder count"""
    if not user_id or user_id == "default":
        return
    conn, _db_type = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE invoices SET
            reminder_count = reminder_count + 1,
            updated_at = %s
        WHERE invoice_number = %s AND user_id = %s
    ''', (datetime.now().isoformat(), invoice_number, user_id))
    conn.commit()
    conn.close()


def get_all_invoices(user_id: str) -> list:
    """Ambil semua invoice milik user"""
    if not user_id or user_id == "default":
        return []
    conn, _db_type = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT invoice_number, customer_name, customer_phone,
               amount, description, due_date, status, reminder_count, created_at
        FROM invoices
        WHERE user_id = %s
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


def send_invoice_wa_manual(invoice_number: str, user_id: str) -> dict:
    """Mode Manual: Kirim WA tagihan sekarang berdasarkan perintah user"""
    if not user_id or user_id == "default":
        return {"status": "error", "message": "User tidak valid"}

    invoice = get_invoice_by_number(invoice_number, user_id)
    if not invoice:
        return {"status": "error", "message": f"Invoice {invoice_number} tidak ditemukan"}

    if invoice["status"] == "paid":
        return {"status": "error", "message": f"Invoice {invoice_number} sudah lunas"}

    phone = invoice.get("customer_phone", "")
    if not phone:
        return {"status": "error", "message": "Nomor WA customer tidak ada di invoice ini"}

    from app.services.whatsapp_service import send_invoice_whatsapp
    result = send_invoice_whatsapp(
        phone=phone,
        customer_name=invoice["customer_name"],
        invoice_number=invoice["invoice_number"],
        amount=invoice["amount"],
        due_date=invoice["due_date"],
        description=invoice.get("description", ""),
        is_reminder=False
    )

    return {
        "status": "success",
        "message": f"WA tagihan berhasil dikirim ke {invoice['customer_name']} ({phone})",
        "wa_result": result
    }


async def extract_invoice_from_command(message: str) -> dict:
    """Extract info invoice dari perintah user pakai AI"""
    from app.services.ai_provider import call_llm

    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    system_prompt = f"""Dari perintah berikut, ekstrak informasi invoice dalam JSON:
{{
    "customer_name": "nama customer",
    "customer_phone": "nomor WA customer format 62xxx tanpa strip/spasi/plus, kosong jika tidak ada",
    "customer_email": "email customer jika ada, kosong jika tidak",
    "amount": 0,
    "description": "deskripsi tagihan",
    "due_date": "tanggal jatuh tempo format YYYY-MM-DD"
}}

Hari ini: {today}
Besok: {tomorrow}

ATURAN NOMINAL — konversi semua format ke angka bulat:
- "500rb" / "500 ribu" / "500k" → 500000
- "1 juta" / "1jt" / "1.000.000" → 1000000
- "1.5 juta" / "1,5 juta" / "1.5jt" → 1500000
- "250rb" → 250000
- "2 juta" → 2000000

ATURAN NOMOR HP — normalisasi ke format 62xxx:
- "08123456789" → "628123456789"
- "+62 813-1249-0171" → "6281312490171"
- "+6281312490171" → "6281312490171"
- "62813-1249-0171" → "6281312490171"
- Hapus semua karakter: +, -, spasi

ATURAN WAKTU:
- "sekarang" / "hari ini" → {today}
- "besok" → {tomorrow}
- "minggu depan" → 7 hari dari sekarang
- "2 minggu" → 14 hari dari sekarang
- "bulan depan" → 30 hari dari sekarang

PENTING:
- Jika tidak ada nama customer yang jelas → customer_name: ""
- Jika tidak ada nominal → amount: 0
- Jangan pernah return amount: 0 jika ada angka di pesan

Respond HANYA dengan JSON murni tanpa backtick."""

    try:
        response = await call_llm(system_prompt, message)
        clean = response.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean)

        # ✅ Normalize nomor sebagai safety net
        phone = data.get("customer_phone", "")
        if phone:
            phone = phone.replace("+", "").replace("-", "").replace(" ", "")
            if phone.startswith("0"):
                phone = "62" + phone[1:]
            elif not phone.startswith("62"):
                phone = "62" + phone
            data["customer_phone"] = phone

        return data
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