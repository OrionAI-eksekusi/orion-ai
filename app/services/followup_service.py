"""
APEX Follow Up Service
Auto follow up leads yang belum reply dalam 24 jam
Fixed: indentation, SQL params, cursor scope, asyncio.to_thread
"""
import asyncio
import httpx
import os

WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "https://worker-production-67d8.up.railway.app")

FOLLOW_UP_MESSAGES = [
    "Halo {name}! 😊 Gimana, ada yang bisa kami bantu lagi? Kami siap melayani kamu!",
    "Hei {name}! Masih ada pertanyaan tentang produk kami? Jangan ragu untuk tanya ya! 🙏",
    "Halo {name}! Kami punya promo spesial hari ini — mau tau detailnya? 🎁",
]


def _fetch_leads():
    from app.services.database_service import get_connection
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT l.user_id, l.phone, l.name, l.current_state,
                   l.follow_up_count, l.last_contact
            FROM leads l
            JOIN wa_sessions ws ON ws.user_id = l.user_id AND ws.is_active = true
            WHERE l.current_state NOT IN ('CLOSED_WON', 'CLOSED_LOST', 'HUMAN_REQUIRED')
              AND l.last_contact < NOW() - INTERVAL '24 hours'
              AND l.follow_up_count < 3
            ORDER BY l.last_contact ASC
            LIMIT 50
        """)
        return c.fetchall()
    finally:
        conn.close()


def _update_lead_followup(user_id: str, phone: str):
    from app.services.database_service import get_connection
    conn, _ = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE leads
            SET follow_up_count = follow_up_count + 1,
                last_contact    = NOW(),
                updated_at      = NOW()
            WHERE user_id = %s AND phone = %s
        """, (user_id, phone))
        conn.commit()
    finally:
        conn.close()


async def send_follow_up(lead: tuple):
    user_id        = lead[0]
    phone          = lead[1]
    name           = lead[2] or "Kak"
    follow_up_count = lead[4] or 0

    first_name   = name.split()[0] if name else "Kak"
    msg_template = FOLLOW_UP_MESSAGES[min(follow_up_count, len(FOLLOW_UP_MESSAGES) - 1)]
    message      = msg_template.format(name=first_name)

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            res = await http.post(f"{WA_GATEWAY_URL}/send-message", json={
                "user_id": user_id,
                "phone":   phone,
                "message": message,
            })

        if res.status_code == 200:
            await asyncio.to_thread(_update_lead_followup, user_id, phone)
            print(f"[FOLLOWUP] ✅ {phone} — follow up #{follow_up_count + 1}")
        else:
            print(f"[FOLLOWUP] ❌ Gagal kirim ke {phone} — status {res.status_code}")

    except Exception as e:
        print(f"[FOLLOWUP] Error {phone}: {e}")


async def run_follow_up():
    try:
        leads = await asyncio.to_thread(_fetch_leads)
        print(f"[FOLLOWUP] {len(leads)} leads perlu follow up")

        await asyncio.gather(*[send_follow_up(lead) for lead in leads])

    except Exception as e:
        print(f"[FOLLOWUP] run_follow_up error: {e}")
