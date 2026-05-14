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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM vendor_transactions WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM vendor_profiles WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM risk_alerts WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM compliance_audit_trail WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM investigation_log WHERE user_id = ?", (user_id,))
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
