from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/zenith", tags=["zenith"])


class PriceGuardRequest(BaseModel):
    user_id: str
    vendor_name: str
    item_description: str
    unit_price: float
    quantity: float = 1.0
    category: str = "general"
    invoice_number: str = ""


class VendorAnalysisRequest(BaseModel):
    user_id: str
    vendor_name: str


class ResolveAlertRequest(BaseModel):
    alert_id: int
    user_id: str


@router.post("/price-guard")
async def price_guard(request: PriceGuardRequest):
    """✅ Analisa harga vendor — deteksi markup"""
    try:
        from app.services.zenith_service import analyze_price_guard
        result = await analyze_price_guard(
            user_id=request.user_id,
            vendor_name=request.vendor_name,
            item_description=request.item_description,
            unit_price=request.unit_price,
            quantity=request.quantity,
            category=request.category
        )
        return {"status": "success", "analysis": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/anomalies/{user_id}")
async def get_anomalies(user_id: str):
    """✅ Deteksi anomali transaksi"""
    try:
        from app.services.zenith_service import detect_transaction_anomalies
        result = await detect_transaction_anomalies(user_id)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/dashboard/{user_id}")
async def executive_dashboard(user_id: str):
    """✅ Executive Dashboard data"""
    try:
        from app.services.zenith_service import get_executive_dashboard
        data = get_executive_dashboard(user_id)
        return {"status": "success", "dashboard": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/vendor-intelligence")
async def vendor_intelligence(request: VendorAnalysisRequest):
    """✅ Deep analisa vendor"""
    try:
        from app.services.zenith_service import analyze_vendor
        result = await analyze_vendor(request.user_id, request.vendor_name)
        return {"status": "success", "intelligence": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/alerts/{user_id}")
async def get_alerts(user_id: str, status: str = "open"):
    """✅ Ambil risk alerts"""
    try:
        from app.services.zenith_service import get_risk_alerts
        alerts = get_risk_alerts(user_id, status)
        return {"status": "success", "alerts": alerts, "count": len(alerts)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/alerts/resolve")
async def resolve_alert_endpoint(request: ResolveAlertRequest):
    """✅ Resolve alert"""
    try:
        from app.services.zenith_service import resolve_alert
        resolve_alert(request.alert_id, request.user_id)
        return {"status": "success", "message": "Alert resolved"}
    except Exception as e:
        return {"status": "error", "message": str(e)}