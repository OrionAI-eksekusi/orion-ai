"""
APEX Multi-Agent Runtime
ETDEM: Event → Thinking → Decision → Execution → Memory
Fixed: asyncio.to_thread, state regression, memory leak, model env var
"""
import asyncio
import os
from typing import Optional
import anthropic

from app.services.context_engine import (
    aggregate_context,
    update_lead_state,
    save_memory,
)

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
BACKEND_URL    = os.getenv("BACKEND_URL", "https://web-production-d2935.up.railway.app")

client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)

# ─── STATE MACHINE ────────────────────────────────────────────────────────────

LEAD_STATE_SIGNALS = {
    "READY_TO_BUY": [
        "mau beli", "mau order", "jadi beli", "transfer ke mana",
        "rekening", "berapa total", "deal", "oke fix", "saya ambil",
        "saya mau", "lanjut", "jadi", "konfirmasi"
    ],
    "NEGOTIATING": [
        "kemahalan", "diskon", "nego", "bisa kurang", "harga terbaik",
        "bisa lebih murah", "kurangin", "tawar"
    ],
    "INTERESTED": [
        "tertarik", "menarik", "info lebih", "ceritain", "detail",
        "pengen tau", "mau tanya", "bisa jelasin"
    ],
    "ASKED_PRICE": [
        "berapa harga", "harganya", "price", "biaya", "tarif",
        "berapa", "cost", "budget"
    ],
}

# Urutan prioritas state — tidak boleh turun kecuali HUMAN_REQUIRED
STATE_PRIORITY = {
    "NEW_LEAD": 0,
    "ASKED_PRICE": 1,
    "INTERESTED": 2,
    "NEGOTIATING": 3,
    "READY_TO_BUY": 4,
    "WAITING_PAYMENT": 5,
    "CLOSED_WON": 6,
    "CLOSED_LOST": 6,
    "HUMAN_REQUIRED": 99,
}

def resolve_state(current_state: str, detected_state: str) -> str:
    """State hanya boleh naik, tidak turun."""
    current_priority  = STATE_PRIORITY.get(current_state, 0)
    detected_priority = STATE_PRIORITY.get(detected_state, 0)
    if detected_priority > current_priority:
        return detected_state
    return current_state


# ─── DETEKSI STATE & SCORE ────────────────────────────────────────────────────

async def detect_lead_state(message: str) -> str:
    msg = message.lower()
    for state, signals in LEAD_STATE_SIGNALS.items():
        if any(s in msg for s in signals):
            return state
    return "NEW_LEAD"


async def calculate_lead_score(message: str, chat_history: list) -> int:
    score = 30
    msg = message.lower()
    if any(s in msg for s in LEAD_STATE_SIGNALS["READY_TO_BUY"]):
        score += 50
    elif any(s in msg for s in LEAD_STATE_SIGNALS["NEGOTIATING"]):
        score += 30
    elif any(s in msg for s in LEAD_STATE_SIGNALS["INTERESTED"]):
        score += 20
    elif any(s in msg for s in LEAD_STATE_SIGNALS["ASKED_PRICE"]):
        score += 10
    score += min(len(chat_history) * 2, 20)
    return min(score, 100)


# ─── TOKEN LOGGING ────────────────────────────────────────────────────────────

async def log_token_usage(user_id: str, usage_type: str, tokens: int):
    def _write():
        from app.services.database_service import get_connection
        conn, _ = get_connection()
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO billing_usages (user_id, usage_type, tokens_used, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (user_id, usage_type, tokens))
            conn.commit()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_write)
    except Exception as e:
        print(f"[AGENT] Token log error: {e}")


# ─── HUMAN HANDOFF NOTIFICATION ───────────────────────────────────────────────

async def notify_human_handoff(user_id: str, phone: str):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as http:
            await http.post(
                f"{BACKEND_URL}/chat/notifications/send",
                json={"user_id": user_id, "type": "human_required", "phone": phone}
            )
    except Exception as e:
        print(f"[HANDOFF] Notify error: {e}")


# ─── MAIN SALES AGENT ─────────────────────────────────────────────────────────

async def run_sales_agent(user_id: str, phone: str, message: str) -> dict:
    """
    APEX Sales Agent Runtime
    ETDEM: Event → Thinking → Decision → Execution → Memory
    """
    try:
        # 1. AGGREGATE CONTEXT (Parallel)
        print(f"[AGENT] Aggregating context for {phone}...")
        context = await aggregate_context(user_id, phone)

        user_profile = context.get("user", {})
        lead         = context.get("lead") or {}
        chat_history = context.get("chat_history", [])
        memory       = context.get("memory", {})
        sop          = context.get("sop", [])

        # 2. DETECT & RESOLVE LEAD STATE
        detected_state  = await detect_lead_state(message)
        current_state   = lead.get("current_state", "NEW_LEAD")
        resolved_state  = resolve_state(current_state, detected_state)
        lead_score      = await calculate_lead_score(message, chat_history)

        # 3. BUILD SYSTEM PROMPT
        business_name    = user_profile.get("business_name") or "bisnis ini"
        business_context = user_profile.get("business_context") or ""

        sop_text = "\n".join(
            [f"- {s['sop_type']}: {s['content']}" for s in sop]
        ) if sop else "Tidak ada SOP tersedia."

        memory_text = "\n".join(
            [f"- {k}: {v}" for k, v in memory.items()]
        ) if memory else "Belum ada data customer."

        history_text = "\n".join([
            f"Customer: {h['message']}" for h in chat_history[-10:]
        ]) if chat_history else "Percakapan baru."

        system_prompt = f"""Kamu adalah Sales AI kelas dunia untuk {business_name}.

IDENTITAS:
- Hangat, cerdas, natural seperti sahabat yang expert
- Bahasa Indonesia santai tapi profesional
- Selalu ada energi positif dan helpful
- JANGAN pernah sebut bahwa kamu AI

KONTEKS BISNIS:
{business_context}

SOP & PRODUK:
{sop_text}

DATA CUSTOMER:
{memory_text}

HISTORI PERCAKAPAN:
{history_text}

STATUS LEAD: {resolved_state}
LEAD SCORE: {lead_score}/100

INSTRUKSI:
- Jawab natural, maksimal 3 kalimat
- Jika READY_TO_BUY → berikan info pembayaran & konfirmasi
- Jika tanya harga → berikan dari SOP, jangan bilang "hubungi kami"
- Selalu akhiri dengan pertanyaan engaging
- Jika ada keluhan berat → empati dulu, baru solusi"""

        # 4. CALL CLAUDE AI
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": message}]
        )
        reply = response.content[0].text

        # 5. HUMAN HANDOFF CHECK
        needs_human = False
        human_triggers = [
            "marah", "komplain", "tipu", "bohong", "lapor",
            "hukum", "brengsek", "refund", "mau lapor", "ancam"
        ]
        if any(t in message.lower() for t in human_triggers):
            needs_human    = True
            resolved_state = "HUMAN_REQUIRED"
            reply = "Mohon maaf atas ketidaknyamanannya kak 🙏 Tim kami akan segera membantu!"
            print(f"[HANDOFF] 🚨 Human required for {phone}")
            asyncio.create_task(notify_human_handoff(user_id, phone))

        # 6. UPDATE LEAD STATE & MEMORY
        await update_lead_state(user_id, phone, resolved_state, {
            "lead_score": lead_score,
            "memories": {
                "last_message": message[:100],
                "last_reply":   reply[:100],
                "lead_state":   resolved_state,
            }
        })

        # 7. LOG TOKEN USAGE
        tokens = response.usage.input_tokens + response.usage.output_tokens
        asyncio.create_task(log_token_usage(user_id, "wa_reply", tokens))
        print(f"[AGENT] ✅ {phone} | {current_state}→{resolved_state} | Score:{lead_score} | Tokens:{tokens}")

        # 8. AUTO PDF QUOTATION jika READY_TO_BUY
        if resolved_state == "READY_TO_BUY" and current_state != "READY_TO_BUY":
            try:
                from app.services.pdf_service import generate_and_send_quotation
                from app.services.database_service import get_connection

                def _get_sop_items():
                    conn, _ = get_connection()
                    try:
                        c = conn.cursor()
                        c.execute("""
                            SELECT content FROM workspace_sop
                            WHERE user_id = %s AND sop_type = 'produk'
                            LIMIT 1
                        """, (user_id,))
                        row = c.fetchone()
                        return row[0] if row else None
                    finally:
                        conn.close()

                sop_content = await asyncio.to_thread(_get_sop_items)
                items = [{"name": sop_content or "Produk/Layanan", "qty": 1, "price": 0}]

                asyncio.create_task(generate_and_send_quotation(
                    user_id=user_id,
                    phone=phone,
                    customer_name=memory.get("customer_name", "Customer"),
                    items=items,
                    notes="Tim kami akan mengkonfirmasi harga final segera.",
                    business_name=business_name,
                ))
                print(f"[AGENT] 📄 PDF quotation triggered for {phone}")
            except Exception as pdf_err:
                print(f"[AGENT] PDF error: {pdf_err}")

        return {
            "reply":       reply,
            "lead_state":  resolved_state,
            "lead_score":  lead_score,
            "needs_human": needs_human,
        }

    except Exception as e:
        print(f"[AGENT] ❌ Error: {e}")
        return {
            "reply":       "Terima kasih atas pesan Anda! Kami akan segera membalas. 🙏",
            "lead_state":  "NEW_LEAD",
            "lead_score":  0,
            "needs_human": False,
        }
