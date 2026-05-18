"""
APEX Payment Service
iPaymu integration + Invoice Management System
"""
import hashlib
import hmac
import json
import os
import re
import asyncio
import httpx
from datetime import datetime, timedelta
from app.services.database_service import get_connection

IPAYMU_VA      = os.getenv("IPAYMU_VA", "")
IPAYMU_API_KEY = os.getenv("IPAYMU_API_KEY", "")
IPAYMU_URL     = os.getenv("IPAYMU_URL", "https://my.ipaymu.com/api/v2")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "https://orion-ai-web.vercel.app")
BACKEND_URL    = os.getenv("BACKEND_URL", "https://web-production-d2935.up.railway.app")

PLANS = {
    "apex":   {"name": "Orion AI APEX",   "price": 120000},
    "zenith": {"name": "Orion AI ZENITH", "price": 135000},
}


# ─── UTILS ────────────────────────────────────────────────────────────────────

def format_amount(amount: float) -> str:
    """Format angka ke Rupiah — contoh: 1500000 → Rp 1.500.000"""
    try:
        return f"Rp {int(amount):,}".replace(",", ".")
    except:
        return f"Rp {amount}"


def _generate_invoice_number() -> str:
    return f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"


# ─── DB INIT ──────────────────────────────────────────────────────────────────

def init_payment_db():
    """Buat tabel invoices kalau belum ada"""
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id               SERIAL PRIMARY KEY,
                user_id          TEXT NOT NULL,
                invoice_number   TEXT UNIQUE NOT NULL,
                customer_name    TEXT NOT NULL,
                customer_phone   TEXT DEFAULT '',
                customer_email   TEXT DEFAULT '',
                amount           NUMERIC NOT NULL,
                description      TEXT DEFAULT '',
                due_date         TEXT DEFAULT '',
                status           TEXT DEFAULT 'unpaid',
                reminder_count   INTEGER DEFAULT 0,
                paid_at          TIMESTAMP,
                created_at       TIMESTAMP DEFAULT NOW(),
                updated_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ─── CRUD INVOICE ─────────────────────────────────────────────────────────────

def create_invoice(
    user_id: str,
    customer_name: str,
    amount: float,
    due_date: str = "",
    description: str = "Tagihan",
    customer_phone: str = "",
    customer_email: str = ""
) -> dict:
    """Buat invoice baru"""
    init_payment_db()
    invoice_number = _generate_invoice_number()
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO invoices
                (user_id, invoice_number, customer_name, customer_phone,
                 customer_email, amount, description, due_date, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'unpaid')
            RETURNING id
        """, (user_id, invoice_number, customer_name, customer_phone,
              customer_email, amount, description, due_date))
        conn.commit()
        return {
            "invoice_number": invoice_number,
            "customer_name":  customer_name,
            "amount":         amount,
            "due_date":       due_date,
            "description":    description,
            "customer_phone": customer_phone,
            "status":         "unpaid",
        }
    finally:
        conn.close()


def get_all_invoices(user_id: str) -> list:
    """Ambil semua invoice user"""
    init_payment_db()
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT invoice_number, customer_name, customer_phone,
                   amount, description, due_date, status, reminder_count, created_at
            FROM invoices
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        rows = c.fetchall()
        return [{
            "invoice_number": r[0], "customer_name":  r[1],
            "customer_phone": r[2], "amount":         float(r[3]),
            "description":    r[4], "due_date":       r[5],
            "status":         r[6], "reminder_count": r[7],
            "created_at":     str(r[8]),
        } for r in rows]
    finally:
        conn.close()


def get_unpaid_invoices(user_id: str) -> list:
    """Ambil invoice yang belum lunas"""
    init_payment_db()
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT invoice_number, customer_name, customer_phone,
                   amount, description, due_date, reminder_count
            FROM invoices
            WHERE user_id = %s AND status = 'unpaid'
            ORDER BY due_date ASC
        """, (user_id,))
        rows = c.fetchall()
        return [{
            "invoice_number": r[0], "customer_name":  r[1],
            "customer_phone": r[2], "amount":         float(r[3]),
            "description":    r[4], "due_date":       r[5],
            "reminder_count": r[6],
        } for r in rows]
    finally:
        conn.close()


def get_due_invoices(user_id: str) -> list:
    """Ambil invoice yang sudah jatuh tempo dan belum lunas — max reminder 3x"""
    init_payment_db()
    today = datetime.now().strftime("%Y-%m-%d")
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT invoice_number, customer_name, customer_phone,
                   amount, description, due_date, reminder_count
            FROM invoices
            WHERE user_id = %s
              AND status = 'unpaid'
              AND due_date != ''
              AND due_date <= %s
              AND reminder_count < 3
            ORDER BY due_date ASC
        """, (user_id, today))
        rows = c.fetchall()
        return [{
            "invoice_number": r[0], "customer_name":  r[1],
            "customer_phone": r[2], "amount":         float(r[3]),
            "description":    r[4], "due_date":       r[5],
            "reminder_count": r[6],
        } for r in rows]
    finally:
        conn.close()


def get_invoice_by_number(invoice_number: str, user_id: str) -> dict:
    """Ambil satu invoice berdasarkan nomor"""
    init_payment_db()
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT invoice_number, customer_name, customer_phone,
                   amount, description, due_date, status, reminder_count
            FROM invoices
            WHERE invoice_number = %s AND user_id = %s
        """, (invoice_number, user_id))
        row = c.fetchone()
        if not row:
            return {}
        return {
            "invoice_number": row[0], "customer_name":  row[1],
            "customer_phone": row[2], "amount":         float(row[3]),
            "description":    row[4], "due_date":       row[5],
            "status":         row[6], "reminder_count": row[7],
        }
    finally:
        conn.close()


def mark_invoice_paid(invoice_number: str, user_id: str) -> bool:
    """Tandai invoice sebagai lunas"""
    init_payment_db()
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE invoices
            SET status = 'paid', paid_at = NOW(), updated_at = NOW()
            WHERE invoice_number = %s AND user_id = %s AND status = 'unpaid'
        """, (invoice_number, user_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def increment_reminder_count(invoice_number: str, user_id: str):
    """Tambah counter reminder invoice"""
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE invoices
            SET reminder_count = reminder_count + 1, updated_at = NOW()
            WHERE invoice_number = %s AND user_id = %s
        """, (invoice_number, user_id))
        conn.commit()
    finally:
        conn.close()


# ─── AI EXTRACT ───────────────────────────────────────────────────────────────

async def extract_invoice_from_command(message: str) -> dict:
    """Ekstrak info invoice dari perintah natural language pakai AI"""
    try:
        from app.services.ai_provider import call_llm, parse_json_response
        today = datetime.now().strftime("%Y-%m-%d")
        system_prompt = f"""Ekstrak informasi tagihan dari perintah user.
Hari ini: {today}
Jawab HANYA JSON murni:
{{
    "customer_name": "nama customer",
    "customer_phone": "nomor WA dengan format 62xxx atau kosong",
    "customer_email": "email atau kosong",
    "amount": 0,
    "description": "keterangan tagihan",
    "due_date": "YYYY-MM-DD atau kosong"
}}
Konversi: 500rb=500000, 1jt=1000000, 1.5jt=1500000
Konversi due_date: besok={( datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d')}, minggu depan={(datetime.now()+timedelta(days=7)).strftime('%Y-%m-%d')}"""
        response = await call_llm(system_prompt, message)
        return parse_json_response(response) or {}
    except Exception as e:
        print(f"[EXTRACT INVOICE ERROR] {e}")
        return {}


# ─── SEND INVOICE VIA WA ──────────────────────────────────────────────────────

def send_invoice_wa_manual(invoice_number: str, user_id: str) -> dict:
    """Kirim invoice ke customer via WA secara manual"""
    inv = get_invoice_by_number(invoice_number, user_id)
    if not inv:
        return {"status": "error", "message": f"Invoice {invoice_number} tidak ditemukan"}
    if not inv.get("customer_phone"):
        return {"status": "error", "message": "Customer tidak punya nomor WA"}
    from app.services.whatsapp_service import send_invoice_whatsapp
    result = send_invoice_whatsapp(
        phone=inv["customer_phone"],
        customer_name=inv["customer_name"],
        invoice_number=invoice_number,
        amount=inv["amount"],
        due_date=inv["due_date"],
        description=inv["description"],
        is_reminder=False,
        user_id=user_id,
    )
    return {"status": "success", "message": f"Invoice {invoice_number} terkirim ke {inv['customer_name']}"}


# ─── IPAYMU PAYMENT ───────────────────────────────────────────────────────────

def _generate_signature(body: dict) -> str:
    body_str  = json.dumps(body, separators=(",", ":"))
    body_hash = hashlib.sha256(body_str.encode()).hexdigest()
    string_to_sign = f"POST:{IPAYMU_VA}:{body_hash}:{IPAYMU_API_KEY}"
    return hmac.new(
        IPAYMU_API_KEY.encode(),
        string_to_sign.encode(),
        hashlib.sha256
    ).hexdigest().lower()


async def create_payment(user_id: str, plan: str, user_email: str, user_name: str) -> dict:
    """Buat payment iPaymu untuk upgrade plan"""
    try:
        if plan not in PLANS:
            return {"status": "error", "message": "Plan tidak valid"}
        plan_info = PLANS[plan]
        order_id  = f"ORION-{user_id}-{plan}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        body = {
            "name":          user_name,
            "phone":         "",
            "email":         user_email,
            "amount":        str(plan_info["price"]),
            "notifyUrl":     f"{BACKEND_URL}/chat/payment-webhook",
            "comments":      f"Orion AI {plan.upper()} - 1 bulan",
            "referenceId":   order_id,
            "paymentMethod": "va",
            "paymentChannel": "bca",
        }
        headers = {
            "Content-Type": "application/json",
            "va":            IPAYMU_VA,
            "signature":     _generate_signature(body),
            "timestamp":     datetime.now().strftime("%Y%m%d%H%M%S"),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            res  = await client.post(f"{IPAYMU_URL}/payment/direct", json=body, headers=headers)
            data = res.json()
            if data.get("Status") == 200:
                return {"status": "success", "payment_url": data["Data"]["Url"], "order_id": order_id}
            else:
                return {"status": "error", "message": data.get("Message", "Payment gagal")}
    except Exception as e:
        return {"status": "error", "message": str(e)}
