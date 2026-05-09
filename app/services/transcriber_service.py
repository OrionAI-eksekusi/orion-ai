import os
import json
import tempfile
from groq import Groq
from app.services.ai_provider import call_llm

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


async def transcribe_audio(audio_path: str, language: str = "id") -> str:
    """Transkrip audio menggunakan Groq Whisper"""
    try:
        client = Groq(api_key=GROQ_API_KEY)

        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), audio_file.read()),
                model="whisper-large-v3",
                language=language,
                response_format="verbose_json",
            )

        return transcription.text

    except Exception as e:
        print(f"[TRANSCRIBE ERROR] {e}")
        raise e


async def analyze_meeting(transcript: str, meeting_title: str = "Meeting") -> dict:
    """Analisa transkrip meeting menggunakan Claude AI"""

    system_prompt = """Kamu adalah asisten notulen meeting profesional.
Analisa transkrip meeting berikut dan buat ringkasan terstruktur.

Jawab HANYA dengan JSON murni tanpa backtick:
{
    "title": "judul meeting",
    "summary": "ringkasan singkat meeting 2-3 kalimat",
    "participants": ["nama peserta 1", "nama peserta 2"],
    "key_points": [
        "poin penting 1",
        "poin penting 2"
    ],
    "decisions": [
        "keputusan yang diambil 1",
        "keputusan yang diambil 2"
    ],
    "action_items": [
        {
            "person": "nama yang bertanggung jawab",
            "task": "tugas yang harus dikerjakan",
            "deadline": "deadline jika disebutkan, kosong jika tidak"
        }
    ],
    "next_meeting": "jadwal meeting berikutnya jika ada, kosong jika tidak"
}"""

    try:
        response = await call_llm(system_prompt,
            f"Judul Meeting: {meeting_title}\n\nTranskrip:\n{transcript}")
        clean = response.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except Exception as e:
        print(f"[ANALYZE ERROR] {e}")
        return {
            "title": meeting_title,
            "summary": transcript[:200],
            "participants": [],
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "next_meeting": ""
        }


def format_meeting_summary(analysis: dict, transcript: str) -> str:
    """Format ringkasan meeting jadi teks yang siap dikirim"""
    from datetime import datetime

    now = datetime.now().strftime("%d %B %Y %H:%M")

    text = f"""📋 NOTULEN MEETING — {analysis.get('title', 'Meeting')}
📅 Tanggal: {now}
━━━━━━━━━━━━━━━━━━━━━━

📝 RINGKASAN:
{analysis.get('summary', '')}

👥 PESERTA:
{chr(10).join(f"• {p}" for p in analysis.get('participants', [])) or '• Tidak terdeteksi'}

📌 POIN PENTING:
{chr(10).join(f"• {p}" for p in analysis.get('key_points', [])) or '• Tidak ada'}

✅ KEPUTUSAN:
{chr(10).join(f"• {d}" for d in analysis.get('decisions', [])) or '• Tidak ada keputusan'}

🎯 ACTION ITEMS:
"""

    action_items = analysis.get('action_items', [])
    if action_items:
        for item in action_items:
            deadline = f" — ⏰ {item['deadline']}" if item.get('deadline') else ""
            text += f"• {item.get('person', '?')}: {item.get('task', '')}{deadline}\n"
    else:
        text += "• Tidak ada action items\n"

    if analysis.get('next_meeting'):
        text += f"\n📅 MEETING BERIKUTNYA:\n{analysis['next_meeting']}\n"

    text += f"""
━━━━━━━━━━━━━━━━━━━━━━
🤖 Notulen ini dibuat otomatis oleh Orion AI"""

    return text


def format_meeting_wa(analysis: dict) -> str:
    """Format ringkasan meeting yang lebih ringkas untuk WA"""
    from datetime import datetime
    now = datetime.now().strftime("%d %B %Y %H:%M")

    text = f"""📋 *NOTULEN MEETING*
*{analysis.get('title', 'Meeting')}*
📅 {now}

📝 *Ringkasan:*
{analysis.get('summary', '')}

🎯 *Action Items:*
"""
    action_items = analysis.get('action_items', [])
    if action_items:
        for item in action_items:
            deadline = f" _(⏰ {item['deadline']})_" if item.get('deadline') else ""
            text += f"• *{item.get('person', '?')}*: {item.get('task', '')}{deadline}\n"
    else:
        text += "• Tidak ada action items\n"

    if analysis.get('next_meeting'):
        text += f"\n📅 *Meeting Berikutnya:*\n{analysis['next_meeting']}\n"

    text += "\n_Notulen otomatis oleh Orion AI_ 🤖"
    return text


async def process_meeting(
    audio_path: str,
    meeting_title: str = "Meeting",
    participant_emails: list = [],
    participant_phones: list = [],
    language: str = "id"
) -> dict:
    """
    Full pipeline: audio → transkrip → analisa → kirim email + WA
    Returns: dict dengan transkrip, analisa, dan summary
    """
    try:
        # Step 1: Transkrip audio
        print(f"[MEETING] Mentranskrip audio...")
        transcript = await transcribe_audio(audio_path, language)
        print(f"[MEETING] Transkrip selesai: {len(transcript)} karakter")

        # Step 2: Analisa meeting
        print(f"[MEETING] Menganalisa meeting...")
        analysis = await analyze_meeting(transcript, meeting_title)

        # Step 3: Format summary
        summary_text = format_meeting_summary(analysis, transcript)
        wa_text = format_meeting_wa(analysis)

        emails_sent = 0
        wa_sent = 0

        # Step 4: Kirim ke peserta via email
        if participant_emails:
            from app.services.gmail_service import send_email
            for email in participant_emails:
                try:
                    send_email(
                        to=email,
                        subject=f"📋 Notulen: {meeting_title}",
                        body=summary_text
                    )
                    emails_sent += 1
                    print(f"[MEETING] Notulen terkirim ke email {email}")
                except Exception as e:
                    print(f"[MEETING EMAIL ERROR] {email}: {e}")

        # ✅ Step 5: Kirim ke peserta via WA
        if participant_phones:
            from app.services.whatsapp_service import send_whatsapp_baileys
            for phone in participant_phones:
                try:
                    # Normalize nomor
                    phone_clean = phone.strip().replace(" ", "").replace("-", "")
                    if phone_clean.startswith("0"):
                        phone_clean = "62" + phone_clean[1:]
                    elif not phone_clean.startswith("62"):
                        phone_clean = "62" + phone_clean

                    send_whatsapp_baileys(phone_clean, wa_text)
                    wa_sent += 1
                    print(f"[MEETING] Notulen terkirim ke WA {phone_clean}")
                except Exception as e:
                    print(f"[MEETING WA ERROR] {phone}: {e}")

        return {
            "status": "success",
            "transcript": transcript,
            "analysis": analysis,
            "summary": summary_text,
            "emails_sent": emails_sent,
            "wa_sent": wa_sent
        }

    except Exception as e:
        print(f"[MEETING ERROR] {e}")
        return {
            "status": "error",
            "message": str(e),
            "transcript": "",
            "analysis": {},
            "summary": "",
            "emails_sent": 0,
            "wa_sent": 0
        }