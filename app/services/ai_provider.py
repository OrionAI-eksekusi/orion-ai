import os
import re
import json
import logging
import asyncio
import time
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

AI_PROVIDER    = os.getenv("AI_PROVIDER", "claude").strip()
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

GROQ_MODEL   = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# ── Circuit Breaker State ─────────────────────────────────
_circuit = {
    "claude":  {"failures": 0, "last_failure": 0, "open": False},
    "groq":    {"failures": 0, "last_failure": 0, "open": False},
}
_FAILURE_THRESHOLD = 5
_RECOVERY_TIMEOUT  = 30

# ── Request Stats ─────────────────────────────────────────
_stats = defaultdict(lambda: {"success": 0, "failure": 0, "latency_ms": []})

ORION_GLOBAL_SYSTEM = """Kamu adalah Orion AI — asisten eksekusi bisnis yang sangat cerdas, teliti, dan profesional.

KARAKTER ORION:
- Sangat pintar dan analitis — selalu berpikir sebelum menjawab
- Teliti dan akurat — tidak pernah mengarang atau asal jawab
- Profesional tapi tetap hangat dan friendly
- Proaktif — kalau melihat ada yang kurang, langsung kasih saran
- Efisien — jawab to the point, tidak bertele-tele
- Bahasa Indonesia yang baik, santai tapi tetap sopan

PRINSIP UTAMA:
1. Kalau tidak tahu → jujur bilang tidak tahu, jangan mengarang
2. Kalau data tidak lengkap → minta klarifikasi dengan sopan
3. Selalu berikan jawaban yang actionable dan konkret
4. Prioritaskan akurasi di atas kecepatan
5. Kalau ada potensi masalah → langsung ingatkan user"""


# ── Circuit Breaker ───────────────────────────────────────
def _is_circuit_open(provider: str) -> bool:
    if provider not in _circuit:
        return False
    cb = _circuit[provider]
    if not cb["open"]:
        return False
    if time.time() - cb["last_failure"] > _RECOVERY_TIMEOUT:
        logger.info(f"[CIRCUIT] {provider.upper()} circuit HALF-OPEN — mencoba lagi...")
        cb["open"] = False
        cb["failures"] = 0
        return False
    return True


def _record_failure(provider: str):
    if provider not in _circuit:
        return
    cb = _circuit[provider]
    cb["failures"] += 1
    cb["last_failure"] = time.time()
    _stats[provider]["failure"] += 1
    if cb["failures"] >= _FAILURE_THRESHOLD:
        if not cb["open"]:
            logger.warning(f"[CIRCUIT] {provider.upper()} circuit OPEN!")
        cb["open"] = True


def _record_success(provider: str, latency_ms: float):
    if provider not in _circuit:
        return
    cb = _circuit[provider]
    cb["failures"] = 0
    cb["open"] = False
    _stats[provider]["success"] += 1
    _stats[provider]["latency_ms"].append(latency_ms)
    if len(_stats[provider]["latency_ms"]) > 100:
        _stats[provider]["latency_ms"] = _stats[provider]["latency_ms"][-100:]


def get_health_status() -> dict:
    status = {}
    for provider in ["claude", "groq"]:
        cb = _circuit[provider]
        latencies = _stats[provider]["latency_ms"]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        status[provider] = {
            "circuit": "OPEN" if cb["open"] else "CLOSED",
            "failures": cb["failures"],
            "success_count": _stats[provider]["success"],
            "failure_count": _stats[provider]["failure"],
            "avg_latency_ms": round(avg_latency, 2),
            "healthy": not cb["open"],
        }
    return status


# ── LLM Callers ───────────────────────────────────────────
async def _call_groq(system_prompt: str, user_message: str) -> str:
    if _is_circuit_open("groq"):
        raise RuntimeError("Groq circuit breaker OPEN")

    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY tidak ada")

    start = time.time()
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        full_system = f"{ORION_GLOBAL_SYSTEM}\n\n{system_prompt}".strip()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user",   "content": user_message}
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        result = response.choices[0].message.content
        _record_success("groq", (time.time() - start) * 1000)
        return result
    except Exception as e:
        _record_failure("groq")
        raise e


async def _call_claude(system_prompt: str, user_message: str) -> str:
    if _is_circuit_open("claude"):
        raise RuntimeError("Claude circuit breaker OPEN")

    if not CLAUDE_API_KEY:
        raise ValueError("CLAUDE_API_KEY tidak ada")

    start = time.time()
    try:
        import httpx
        full_system = f"{ORION_GLOBAL_SYSTEM}\n\n{system_prompt}".strip()
        headers = {
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": 2048,
            "temperature": 0.3,
            "system": full_system,
            "messages": [{"role": "user", "content": user_message}]
        }
        async with httpx.AsyncClient(timeout=90) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload
            )
            if res.status_code != 200:
                logger.error(f"[CLAUDE] HTTP {res.status_code}: {res.text}")
                raise ValueError(f"Claude HTTP {res.status_code}: {res.text}")
            data = res.json()
            result = data["content"][0]["text"]
            _record_success("claude", (time.time() - start) * 1000)
            return result
    except Exception as e:
        _record_failure("claude")
        raise e


# ── Main call_llm dengan Self-Healing ────────────────────
async def call_llm(system_prompt: str, user_message: str,
                   max_retries: int = 2) -> str:
    """
    Smart LLM caller:
    - Primary: Claude
    - Fallback: Groq
    - Circuit breaker per provider
    - Auto retry dengan exponential backoff
    """
    provider = AI_PROVIDER.strip().lower()

    # Fallback chain: Claude → Groq only (Gemini dihapus — quota habis)
    if provider == "groq":
        fallback_chain = ["groq", "claude"]
    else:
        fallback_chain = ["claude", "groq"]

    callers = {
        "claude": _call_claude,
        "groq":   _call_groq,
    }

    last_error = None

    for attempt_provider in fallback_chain:
        # Skip kalau circuit open
        if _is_circuit_open(attempt_provider):
            logger.warning(f"[LLM] {attempt_provider.upper()} circuit OPEN, skip")
            continue

        # Skip kalau tidak ada API key
        if attempt_provider == "groq" and not GROQ_API_KEY:
            continue
        if attempt_provider == "claude" and not CLAUDE_API_KEY:
            continue

        caller = callers[attempt_provider]

        # Retry dengan exponential backoff
        for retry in range(max_retries + 1):
            try:
                if retry > 0:
                    wait = 2 ** retry
                    logger.info(f"[LLM] Retry {retry} untuk {attempt_provider.upper()} dalam {wait}s...")
                    await asyncio.sleep(wait)

                if attempt_provider != provider or retry > 0:
                    logger.info(f"[LLM] {'Fallback' if attempt_provider != provider else 'Retry'} → {attempt_provider.upper()}")

                result = await caller(system_prompt, user_message)
                logger.info(f"[LLM] ✅ {attempt_provider.upper()} berhasil")
                return result

            except Exception as e:
                last_error = e
                error_msg = str(e).lower()

                is_rate_limit = any(x in error_msg for x in [
                    "rate limit", "429", "quota", "resource exhausted",
                    "limit exceeded", "tokens per day"
                ])
                is_model_error = any(x in error_msg for x in [
                    "not_found_error", "model", "404"
                ])

                if is_rate_limit or is_model_error:
                    logger.warning(f"[LLM] {attempt_provider.upper()} {'rate limit' if is_rate_limit else 'model error'} → fallback")
                    break
                else:
                    logger.error(f"[LLM] {attempt_provider.upper()} error (attempt {retry+1}): {e}")
                    if retry == max_retries:
                        break

    # Semua provider gagal
    logger.critical(f"[LLM] 🚨 SEMUA PROVIDER GAGAL! Last error: {last_error}")
    return "Maaf, sistem AI sedang mengalami gangguan sementara. Silakan coba lagi dalam beberapa menit."


def parse_json_response(ai_response: str):
    if not ai_response:
        return None

    try:
        clean = ai_response.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except Exception:
        pass

    try:
        match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    try:
        match = re.search(r'\[.*\]', ai_response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    return None