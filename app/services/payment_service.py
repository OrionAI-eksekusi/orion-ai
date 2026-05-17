"""
APEX Payment Service — iPaymu Integration
"""
import httpx
import hashlib
import json
import os
from datetime import datetime

IPAYMU_VA = os.getenv("IPAYMU_VA", "1179001385496808")
IPAYMU_API_KEY = os.getenv("IPAYMU_API_KEY", "62BE1178-F63F-4EC0-B1F7-953DE16C1ED7")
IPAYMU_URL = os.getenv("IPAYMU_URL", "https://my.ipaymu.com/api/v2")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://orion-ai-web.vercel.app")

PLANS = {
    "apex": {"name": "Orion AI APEX", "price": 120000},
    "zenith": {"name": "Orion AI ZENITH", "price": 135000},
}

def generate_signature(body: dict) -> str:
    body_str = json.dumps(body, separators=(',', ':'))
    body_hash = hashlib.sha256(body_str.encode()).hexdigest()
    string_to_sign = f"POST:{IPAYMU_VA}:{body_hash}:{IPAYMU_API_KEY}"
    return hashlib.sha256(string_to_sign.encode()).hexdigest()

async def create_payment(user_id: str, plan: str, user_email: str, user_name: str) -> dict:
    try:
        if plan not in PLANS:
            return {"status": "error", "message": "Plan tidak valid"}

        plan_info = PLANS[plan]
        order_id = f"ORION-{user_id}-{plan}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        body = {
            "product": [plan_info["name"]],
            "qty": [1],
            "price": [plan_info["price"]],
            "amount": plan_info["price"],
            "returnUrl": f"{FRONTEND_URL}/payment/success?order_id={order_id}&plan={plan}&user_id={user_id}",
            "cancelUrl": f"{FRONTEND_URL}/payment/cancel",
            "notifyUrl": f"https://web-production-d2935.up.railway.app/chat/payment-webhook",
            "referenceId": order_id,
            "buyerName": user_name,
            "buyerEmail": user_email,
            "buyerPhone": "",
        }

        headers = {
            "Content-Type": "application/json",
            "va": IPAYMU_VA,
            "signature": generate_signature(body),
            "timestamp": datetime.now().strftime("%Y%m%d%H%M%S"),
        }

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{IPAYMU_URL}/payment", json=body, headers=headers)
            data = res.json()
            if data.get("Status") == 200:
                return {"status": "success", "payment_url": data["Data"]["Url"], "order_id": order_id}
            else:
                return {"status": "error", "message": data.get("Message", "Payment gagal")}
    except Exception as e:
        return {"status": "error", "message": str(e)}
