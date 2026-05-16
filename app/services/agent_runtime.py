"""
APEX Multi-Agent Runtime
Handles AI decision making, tool calling, and execution
"""
import asyncio
import anthropic
import os
from typing import Optional
from app.services.context_engine import (
    aggregate_context,
    update_lead_state,
    save_memory,
)

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)

# Lead state detection keywords
LEAD_STATE_SIGNALS = {
    'READY_TO_BUY': ['mau beli', 'mau order', 'jadi beli', 'transfer ke mana', 
                      'rekening', 'berapa total', 'deal', 'oke fix', 'saya ambil'],
    'NEGOTIATING': ['kemahalan', 'diskon', 'nego', 'bisa kurang', 'harga terbaik'],
    'INTERESTED': ['tertarik', 'menarik', 'info lebih', 'ceritain', 'detail'],
    'ASKED_PRICE': ['berapa harga', 'harganya', 'price', 'biaya', 'tarif'],
}

async def detect_lead_state(message: str) -> str:
    """Detect lead state from message content"""
    message_lower = message.lower()
    for state, signals in LEAD_STATE_SIGNALS.items():
        if any(signal in message_lower for signal in signals):
            return state
    return 'NEW_LEAD'

async def calculate_lead_score(message: str, chat_history: list) -> int:
    """Calculate lead score 0-100 based on signals"""
    score = 30  # Base score
    message_lower = message.lower()
    
    if any(s in message_lower for s in LEAD_STATE_SIGNALS['READY_TO_BUY']):
        score += 50
    elif any(s in message_lower for s in LEAD_STATE_SIGNALS['NEGOTIATING']):
        score += 30
    elif any(s in message_lower for s in LEAD_STATE_SIGNALS['INTERESTED']):
        score += 20
    elif any(s in message_lower for s in LEAD_STATE_SIGNALS['ASKED_PRICE']):
        score += 10
    
    # Boost for conversation length
    score += min(len(chat_history) * 2, 20)
    
    return min(score, 100)

async def run_sales_agent(
    user_id: str,
    phone: str,
    message: str,
) -> dict:
    """
    Main Sales Agent Runtime
    ETDEM: Event → Thinking → Decision → Execution → Memory
    """
    try:
        # 1. AGGREGATE CONTEXT (Parallel)
        print(f"[AGENT] Aggregating context for {phone}...")
        context = await aggregate_context(user_id, phone)
        
        user_profile = context.get('user', {})
        lead = context.get('lead', {})
        chat_history = context.get('chat_history', [])
        memory = context.get('memory', {})
        sop = context.get('sop', [])
        
        # 2. DETECT LEAD STATE
        detected_state = await detect_lead_state(message)
        lead_score = await calculate_lead_score(message, chat_history)
        
        # 3. BUILD SYSTEM PROMPT
        business_name = user_profile.get('business_name', 'bisnis ini')
        business_context = user_profile.get('business_context', '')
        
        sop_text = '\n'.join([f"- {s['sop_type']}: {s['content']}" for s in sop]) if sop else ''
        memory_text = '\n'.join([f"- {k}: {v}" for k, v in memory.items()]) if memory else ''
        history_text = '\n'.join([
            f"Customer: {h['message']}" if not h.get('reply') else f"AI: {h.get('reply', '')}"
            for h in chat_history[-10:]
        ]) if chat_history else ''

        system_prompt = f"""Kamu adalah Sales AI kelas dunia untuk {business_name}.

IDENTITAS:
- Hangat, cerdas, natural seperti sahabat yang expert
- Bahasa Indonesia santai tapi profesional
- Selalu ada energi positif dan helpful

KONTEKS BISNIS:
{business_context}

SOP BISNIS:
{sop_text}

MEMORY CUSTOMER:
{memory_text}

HISTORI PERCAKAPAN:
{history_text}

STATUS LEAD SAAT INI: {lead.get('current_state', 'NEW_LEAD') if lead else 'NEW_LEAD'}
LEAD SCORE: {lead_score}/100

INSTRUKSI:
- Jawab natural, maksimal 3 kalimat
- Jika customer READY_TO_BUY, berikan info pembayaran
- Jika customer bertanya harga, berikan harga dari SOP
- Selalu akhiri dengan pertanyaan engaging
- JANGAN mention bahwa kamu AI"""

        # 4. CALL CLAUDE API
        response = await client.messages.create(
            model="claude-opus-4-5",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": message}]
        )
        
        reply = response.content[0].text

        # 5. UPDATE LEAD STATE & MEMORY
        await update_lead_state(user_id, phone, detected_state, {
            'lead_score': lead_score,
            'memories': {
                'last_message': message[:100],
                'last_reply': reply[:100],
                'detected_state': detected_state,
            }
        })

        # 6. HUMAN HANDOFF CHECK
        needs_human = False
        human_triggers = ['marah', 'komplain', 'tipu', 'bohong', 'lapor', 'hukum']
        if any(t in message.lower() for t in human_triggers):
            needs_human = True
            await update_lead_state(user_id, phone, 'HUMAN_REQUIRED', {})

        print(f"[AGENT] ✅ Reply generated for {phone} | State: {detected_state} | Score: {lead_score}")

        return {
            "reply": reply,
            "lead_state": detected_state,
            "lead_score": lead_score,
            "needs_human": needs_human,
        }

    except Exception as e:
        print(f"[AGENT] ❌ Error: {e}")
        return {
            "reply": "Terima kasih atas pesan Anda! Kami akan segera membalas. 🙏",
            "lead_state": "NEW_LEAD",
            "lead_score": 0,
            "needs_human": False,
        }