from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/zenith", tags=["zenith"])


# ── Request Models ────────────────────────────────────────
class PriceGuardRequest(BaseModel):
    user_id: str
    vendor_name: str
    item_description: str
    unit_price: float
    quantity: float = 1.0
    category: str = "general"
    invoice_number: str = ""
    division: str = ""
    approved_by: str = ""


class VendorAnalysisRequest(BaseModel):
    user_id: str
    vendor_name: str


class ResolveAlertRequest(BaseModel):
    alert_id: int
    user_id: str


class InvestigateRequest(BaseModel):
    user_id: str
    question: str


class OcrForensicRequest(BaseModel):
    user_id: str
    invoice_text: str
    metadata: dict = {}


class VerifyAlertRequest(BaseModel):
    alert_id: int
    user_id: str
    verified_by: str = "admin"
    result: str = "CONFIRMED"


# ── Price Guard ───────────────────────────────────────────
@router.post("/price-guard")
async def price_guard(request: PriceGuardRequest):
    """Analisa harga vendor — deteksi markup dengan AI"""
    try:
        from app.services.zenith_service import analyze_price_guard
        result = await analyze_price_guard(
            user_id=request.user_id,
            vendor_name=request.vendor_name,
            item_description=request.item_description,
            unit_price=request.unit_price,
            quantity=request.quantity,
            category=request.category,
            invoice_number=request.invoice_number,
            division=request.division,
            approved_by=request.approved_by
        )
        return {"status": "success", "analysis": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Transaction Anomaly Engine ────────────────────────────
@router.get("/anomalies/{user_id}")
async def get_anomalies(user_id: str):
    """Deteksi anomali transaksi — split invoice, duplikat, threshold violation"""
    try:
        from app.services.zenith_service import detect_transaction_anomalies
        result = await detect_transaction_anomalies(user_id)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Executive Dashboard ───────────────────────────────────
@router.get("/dashboard/{user_id}")
async def executive_dashboard(user_id: str):
    """Executive Dashboard — overview real-time level direksi"""
    try:
        from app.services.zenith_service import get_executive_dashboard
        data = get_executive_dashboard(user_id)
        return {"status": "success", "dashboard": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Vendor Intelligence ───────────────────────────────────
@router.post("/vendor-intelligence")
async def vendor_intelligence(request: VendorAnalysisRequest):
    """Deep analisa profil dan risiko vendor"""
    try:
        from app.services.zenith_service import analyze_vendor
        result = await analyze_vendor(request.user_id, request.vendor_name)
        return {"status": "success", "intelligence": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Risk Alerts ───────────────────────────────────────────
@router.get("/alerts/{user_id}")
async def get_alerts(user_id: str, status: str = "open"):
    """Ambil risk alerts berdasarkan status"""
    try:
        from app.services.zenith_service import get_risk_alerts
        alerts = get_risk_alerts(user_id, status)
        return {"status": "success", "alerts": alerts, "count": len(alerts)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/alerts/resolve")
async def resolve_alert_endpoint(request: ResolveAlertRequest):
    """Resolve alert yang sudah ditangani"""
    try:
        from app.services.zenith_service import resolve_alert
        resolve_alert(request.alert_id, request.user_id)
        return {"status": "success", "message": "Alert resolved"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── AI Investigator ───────────────────────────────────────
@router.post("/investigate")
async def investigate(request: InvestigateRequest):
    """AI Investigator — Evidence-Based Forensic Reasoning"""
    try:
        if not request.question.strip():
            return {"status": "error", "message": "Pertanyaan tidak boleh kosong"}
        from app.services.zenith_service import ai_investigator
        result = await ai_investigator(request.user_id, request.question)
        return {"status": "success", "investigation": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── OCR Invoice Forensic ──────────────────────────────────
@router.post("/ocr-forensic")
async def ocr_forensic(request: OcrForensicRequest):
    """OCR Invoice Forensic — deteksi manipulasi dokumen"""
    try:
        if not request.invoice_text.strip():
            return {"status": "error", "message": "Teks invoice tidak boleh kosong"}
        from app.services.zenith_service import ocr_invoice_forensic
        result = await ocr_invoice_forensic(
            request.user_id,
            request.invoice_text,
            request.metadata
        )
        return {"status": "success", "forensic": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Procurement Watch ─────────────────────────────────────
@router.get("/procurement/{user_id}")
async def procurement(user_id: str):
    """Procurement Watch — monitor efisiensi pengadaan"""
    try:
        from app.services.zenith_service import procurement_watch
        result = await procurement_watch(user_id)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Compliance Center ─────────────────────────────────────
@router.get("/compliance/{user_id}")
async def compliance(user_id: str):
    """Compliance Center — audit trail dan policy violation"""
    try:
        from app.services.zenith_service import get_compliance_report
        result = get_compliance_report(user_id)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Verify Alert — Feedback Loop ──────────────────────────
@router.post("/verify-alert")
async def verify_alert_endpoint(request: VerifyAlertRequest):
    """Verifikasi hasil AI — feedback loop untuk training"""
    try:
        from app.services.zenith_service import verify_alert
        result = verify_alert(
            request.alert_id,
            request.user_id,
            request.verified_by,
            request.result
        )
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Reset Data ────────────────────────────────────────────
@router.delete("/reset/{user_id}")
async def reset_zenith_data(user_id: str):
    """Reset semua data Zenith user — untuk hapus data test"""
    try:
        from app.services.zenith_service import init_zenith_db
        import sqlite3
        import os
        DB_PATH = os.getenv("DB_PATH", "orion.db")
        init_zenith_db()
        conn, _db_type = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM vendor_transactions WHERE user_id = %s", (user_id,))
        c.execute("DELETE FROM vendor_profiles WHERE user_id = %s", (user_id,))
        c.execute("DELETE FROM risk_alerts WHERE user_id = %s", (user_id,))
        c.execute("DELETE FROM compliance_audit_trail WHERE user_id = %s", (user_id,))
        c.execute("DELETE FROM investigation_log WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Data Zenith {user_id} berhasil direset"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/auto-extract-gmail")
async def auto_extract_gmail(request: Request):
    """Auto extract invoice dari Gmail ke Zenith Price Guard"""
    try:
        body = await request.json()
        user_id = body.get("user_id", "default")
        from app.services.ai_service import auto_extract_invoices_from_gmail
        result = await auto_extract_invoices_from_gmail(user_id)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/ocr-vision")
async def ocr_vision(request: Request):
    """OCR Invoice pakai Claude Vision — foto langsung dianalisa"""
    try:
        body = await request.json()
        user_id = body.get("user_id", "default")
        image_base64 = body.get("image_base64", "")
        if not image_base64:
            return {"status": "error", "message": "Image tidak ada"}

        import httpx, os, json
        CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
        CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

        headers = {
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": 2048,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": """Kamu adalah forensic document examiner untuk Zenith AI.

Analisa invoice/dokumen ini dan jawab dalam JSON:
{
    "extracted_text": "semua teks yang ada di dokumen",
    "forensic_status": "CLEAN/SUSPICIOUS/TAMPERED",
    "risk_score": 0-100,
    "flags": [
        {
            "flag_type": "jenis flag",
            "severity": "HIGH/MEDIUM/LOW",
            "description": "deskripsi temuan",
            "evidence": "bukti spesifik"
        }
    ],
    "transaction_data": {
        "vendor_name": "nama vendor jika ada",
        "item_description": "deskripsi item",
        "unit_price": 0,
        "quantity": 1,
        "total_amount": 0,
        "invoice_number": "nomor invoice"
    },
    "summary": "ringkasan forensik 2-3 kalimat",
    "recommended_actions": ["tindakan yang direkomendasikan"]
}

Cek:
1. Inkonsistensi format angka
2. Total tidak cocok dengan perhitungan
3. Tanggal tidak wajar
4. Font berbeda dalam dokumen
5. Field yang mencurigakan

Respond HANYA dengan JSON."""
                    }
                ]
            }]
        }

        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload
            )
            data = res.json()
            text = data["content"][0]["text"]
            clean = text.replace('```json', '').replace('```', '').strip()
            result = json.loads(clean)

            # Auto analisa forensik lebih dalam
            from app.services.zenith_service import ocr_invoice_forensic
            deep = await ocr_invoice_forensic(user_id, result.get("extracted_text", ""), {})
            result["deep_forensic"] = deep

            # Auto tambah ke Price Guard kalau ada data transaksi
            tx = result.get("transaction_data", {})
            if tx.get("vendor_name") and tx.get("unit_price", 0) > 0:
                from app.services.zenith_service import analyze_price_guard
                price_result = await analyze_price_guard(
                    user_id=user_id,
                    vendor_name=tx["vendor_name"],
                    item_description=tx.get("item_description", ""),
                    unit_price=float(tx.get("unit_price", 0)),
                    quantity=float(tx.get("quantity", 1)),
                    total_amount=float(tx.get("total_amount", 0)),
                )
                result["price_guard"] = price_result

            return {"status": "success", "forensic": result}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/auto-extract-wa")
async def auto_extract_wa(request: Request):
    """Auto extract transaksi dari WA → Zenith Price Guard"""
    try:
        body = await request.json()
        user_id = body.get("user_id", "default")
        from app.services.ai_service import auto_extract_transactions_from_wa
        result = await auto_extract_transactions_from_wa(user_id)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/auto-extract-wa")
async def auto_extract_wa(request: Request):
    try:
        body = await request.json()
        user_id = body.get("user_id", "default")
        from app.services.ai_service import auto_extract_transactions_from_wa
        result = await auto_extract_transactions_from_wa(user_id)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/market-price/seed")
async def seed_market_price(request: Request):
    """Seed data harga pasar default"""
    try:
        body = await request.json()
        secret = body.get("secret", "")
        if secret != "orion-admin-2026":
            return {"status": "error", "message": "Unauthorized"}
        from app.services.zenith_service import seed_market_prices
        seed_market_prices()
        return {"status": "success", "message": "Data harga pasar berhasil ditambahkan"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/market-price/add")
async def add_market_price(request: Request):
    """Tambah data harga pasar manual"""
    try:
        body = await request.json()
        secret = body.get("secret", "")
        if secret != "orion-admin-2026":
            return {"status": "error", "message": "Unauthorized"}
        import sqlite3
        from app.services.database_service import get_connection, DB_PATH
        conn, _db_type = get_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO market_price_reference 
            (item_name, category, min_price, max_price, avg_price, unit, source)
            VALUES (%s, %s, %s, %s, %s, %s, 'manual')
        ''', (
            body.get("item_name"),
            body.get("category", "general"),
            body.get("min_price", 0),
            body.get("max_price", 0),
            body.get("avg_price", 0),
            body.get("unit", "unit"),
        ))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Harga {body.get('item_name')} ditambahkan"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/market-price/list")
async def list_market_prices(category: str = ""):
    """List semua data harga pasar"""
    try:
        import sqlite3
        from app.services.database_service import get_connection, DB_PATH
        conn, _db_type = get_connection()
        c = conn.cursor()
        if category:
            c.execute("SELECT * FROM market_price_reference WHERE category = %s ORDER BY item_name", (category,))
        else:
            c.execute("SELECT * FROM market_price_reference ORDER BY category, item_name")
        rows = c.fetchall()
        conn.close()
        return {"status": "success", "count": len(rows), "prices": [
            {"id": r[0], "item_name": r[1], "category": r[2],
             "min_price": r[3], "max_price": r[4], "avg_price": r[5],
             "unit": r[6], "source": r[7]} for r in rows
        ]}
    except Exception as e:
        return {"status": "error", "message": str(e)}
