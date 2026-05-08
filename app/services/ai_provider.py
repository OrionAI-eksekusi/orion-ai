import os
import json
import re
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

AI_PROVIDER    = os.getenv("AI_PROVIDER", "claude").strip()
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

GROQ_MODEL   = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
CLAUDE_MODEL = "claude-sonnet-4-20250514"


async def _call_groq(system_prompt: str, user_message: str) -> str:
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message}
        ]
    )
    return response.choices[0].message.content


async def _call_gemini(system_prompt: str, user_message: str) -> str:
    import httpx
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY tidak ada")

    url = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\n{user_message}"}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
            "topP": 0.95,
        }
    }

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            logger.error(f"[GEMINI] HTTP {res.status_code}: {res.text}")
            raise ValueError(f"Gemini HTTP {res.status_code}: {res.text}")
        data = res.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError(f"Gemini tidak return candidates: {data}")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError(f"Gemini tidak return parts: {data}")
        return parts[0].get("text", "")


async def _call_claude(system_prompt: str, user_message: str) -> str:
    import httpx
    if not CLAUDE_API_KEY:
        raise ValueError("CLAUDE_API_KEY tidak ada")

    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_message}
        ]
    }

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload
        )
        if res.status_code != 200:
            logger.error(f"[CLAUDE] HTTP {res.status_code}: {res.text}")
            raise ValueError(f"Claude HTTP {res.status_code}: {res.text}")
        data = res.json()
        return data["content"][0]["text"]


async def call_llm(system_prompt: str, user_message: str) -> str:
    provider = AI_PROVIDER.strip().lower()

    try:
        if provider == "groq":
            logger.info("[LLM] Using Groq")
            return await _call_groq(system_prompt, user_message)
        elif provider == "gemini":
            logger.info("[LLM] Using Gemini")
            return await _call_gemini(system_prompt, user_message)
        elif provider == "claude":
            logger.info("[LLM] Using Claude")
            return await _call_claude(system_prompt, user_message)
        else:
            logger.warning(f"[LLM] Provider '{provider}' tidak dikenal, pakai Claude")
            return await _call_claude(system_prompt, user_message)

    except Exception as primary_error:
        error_msg = str(primary_error).lower()
        is_rate_limit = any(x in error_msg for x in [
            "rate limit", "ratelimit", "429", "quota",
            "limit exceeded", "tokens per day", "resource exhausted"
        ])

        if is_rate_limit:
            logger.warning(f"[LLM] {provider.upper()} rate limit! Fallback...")
        else:
            logger.error(f"[LLM] {provider.upper()} error: {primary_error}")

        # Fallback chain: Claude → Groq → Gemini
        if provider != "claude" and CLAUDE_API_KEY:
            try:
                logger.info("[LLM] Fallback ke Claude...")
                result = await _call_claude(system_prompt, user_message)
                logger.info("[LLM] Claude berhasil!")
                return result
            except Exception as claude_error:
                logger.error(f"[LLM] Claude error: {claude_error}")

        if provider != "groq" and GROQ_API_KEY:
            try:
                logger.info("[LLM] Fallback ke Groq...")
                result = await _call_groq(system_prompt, user_message)
                logger.info("[LLM] Groq berhasil!")
                return result
            except Exception as groq_error:
                logger.error(f"[LLM] Groq error: {groq_error}")

        if provider != "gemini" and GEMINI_API_KEY:
            try:
                logger.info("[LLM] Fallback ke Gemini...")
                result = await _call_gemini(system_prompt, user_message)
                logger.info("[LLM] Gemini berhasil!")
                return result
            except Exception as gemini_error:
                logger.error(f"[LLM] Gemini error: {gemini_error}")

        raise RuntimeError(f"Semua LLM gagal. Primary: {primary_error}")


def parse_json_response(ai_response: str):
    try:
        clean = ai_response.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except Exception:
        match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None