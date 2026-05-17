"""
APEX Follow Up Service
Auto follow up leads yang belum reply dalam 24 jam
"""
import httpx
import os
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")
WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "https://worker-production-67d8.up.railway.app")

FOLLOW_UP_MESSAGES = [
    "Halo {name}! 😊 Gimana, ada yang bisa kami bantu lagi? Kami siap melayani kamu!",
    "Hei {name}! Masih ada pertanyaan tentang produk kami? Jangan ragu untuk tanya ya! 🙏",
    "Halo {name}! Kami punya promo spesial hari ini — mau tau detailnya? 🎁",
]

async def run_follow_up():
    """Check semua leads yang belum reply dalam 24 jam dan kirim follow up"""
    try:
        from app.services.database_service import get_connection
    conn, _ = get_connection()
    c = conn.cursor()
        
        # Ambil leads yang belum reply dalam 24 jam
        c.execute("""
            SELECT l.user_id, l.phone, l.name, l.current_state, 
                   l.follow_up_count, l.last_contact,
                   ws.phone as wa_session_phone
            FROM leads l
            JOIN wa_sessions ws ON ws.user_id = l.user_id AND ws.is_active = true
            WHERE l.current_state NOT IN ('CLOSED_WON', 'CLOSED_LOST', 'HUMAN_REQUIRED')
              AND l.last_contact < NOW() - INTERVAL '24 hours'
              AND l.follow_up_count < 3
            ORDER BY l.last_contact ASC
            LIMIT 50
        """)
        
        leads = c.fetchall()
        print(f"[FOLLOWUP] Found {len(leads)} leads to follow up")
        
        for lead in leads:
            await send_follow_up(conn, lead)
        
        conn.commit()
    conn.close()
        
    except Exception as e:
        print(f"[FOLLOWUP] Error: {e}")

async def send_follow_up(conn, lead):
    """Kirim follow up message ke satu lead"""
    try:
        user_id = lead[0]
        phone = lead[1]
        name = lead[2] or 'Kak'
        follow_up_count = lead[4] or 0
        
        # Pilih pesan berdasarkan urutan follow up
        msg_template = FOLLOW_UP_MESSAGES[min(follow_up_count, len(FOLLOW_UP_MESSAGES) - 1)]
        message = msg_template.format(name=name.split()[0] if name else 'Kak')
        
        # Kirim via WA Gateway
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{WA_GATEWAY_URL}/send-message", json={
                "user_id": user_id,
                "phone": phone,
                "message": message
            })
            
            if res.status_code == 200:
                # Update follow up count dan last contact
                c.execute("""
                    UPDATE leads 
                    SET follow_up_count = follow_up_count + 1,
                        last_contact = NOW(),
                        updated_at = NOW()
                    WHERE user_id = $1 AND phone = $2
                """, user_id, phone)
                
                print(f"[FOLLOWUP] ✅ Sent to {phone} (follow up #{follow_up_count + 1})")
            else:
                print(f"[FOLLOWUP] ❌ Failed to send to {phone}")
                
    except Exception as e:
        print(f"[FOLLOWUP] Error sending to {lead[1]}: {e}")